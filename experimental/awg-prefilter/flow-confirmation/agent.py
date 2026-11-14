#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Disposable IPv4 lab: short conntrack leases after exit-authenticated data."""
import argparse
import dataclasses
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import select
import signal
import socket
import ssl
import stat
import struct
import subprocess
import time

TABLE='awg_kernel_guard_lab'
LEASE_SECONDS=10
MAX_PENDING=128
POLL_SECONDS=.1
EVENT=struct.Struct('!4sQ4sH16sQ')

@dataclasses.dataclass(frozen=True)
class Flow:
    source: str
    port: int
    identity: int
    translated_port: int

def parse_conntrack(text,entry,exit,port):
    flows=set()
    for line in text.splitlines():
        tuples=re.findall(r'src=([0-9.]+) dst=([0-9.]+) sport=(\d+) dport=(\d+)',line)
        identity=re.search(r'\bid=(\d+)\b',line)
        if len(tuples)!=2 or not identity:continue
        original,reply=tuples
        if original[1]!=entry or int(original[3])!=port or reply[:2]!=(exit,entry) or int(reply[2])!=port:continue
        address=str(ipaddress.IPv4Address(original[0]))
        values=(int(original[2]),int(identity[1]),int(reply[3]))
        if not (1<=values[0]<=65535 and 0<values[1]<2**32 and 1<=values[2]<=65535):continue
        flows.add(Flow(address,*values))
    assert len(flows)<=4096,'Conntrack lab bound exceeded'
    return flows

def read_flows(config):
    result=subprocess.run(['conntrack','-L','-p','udp','--orig-dst',config['entry'],'--dport',str(config['vpn_port']),'-o','extended,id'],capture_output=True,text=True,timeout=2,check=True)
    return parse_conntrack(result.stdout,config['entry'],config['exit'],config['vpn_port'])

def nonce(value):
    return isinstance(value,str) and re.fullmatch('[0-9a-f]{32}',value) is not None

class Entry:
    def __init__(self):
        self.pending={};self.leases={};self.last_query={};self.peer_stamp={};self.history=[];self.stats={'queries':0,'grants':0,'rejected':0,'moves':0}
    def queries(self,flows,now):
        self.pending={n:v for n,v in self.pending.items() if v[0] in flows and v[1]>now}
        self.leases={f:v for f,v in self.leases.items() if f in flows and v[1]>now}
        self.last_query={f:t for f,t in self.last_query.items() if f in flows}
        busy={v[0] for v in self.pending.values()}
        candidates=sorted(flows,key=lambda f:(f not in self.leases,self.last_query.get(f,-1),f.source,f.port))
        result=[]
        for flow in candidates:
            if flow in busy or now-self.last_query.get(flow,-10)<1 or len(self.pending)>=MAX_PENDING:continue
            if flow in self.leases and self.leases[flow][1]-now>LEASE_SECONDS-2:continue
            request=secrets.token_hex(16)
            self.pending[request]=(flow,now+3);self.last_query[flow]=now
            result.append({'nonce':request,'port':flow.translated_port});self.stats['queries']+=1
            if len(result)==16:break
        return result
    def confirm(self,message,flows,now):
        if set(message)!={'nonce','peer','stamp'} or not nonce(message['nonce']) or not nonce(message['peer']) or type(message['stamp']) is not int or message['stamp']<=0:
            self.stats['rejected']+=1;return False
        pending=self.pending.pop(message['nonce'],None)
        if not pending or pending[0] not in flows or pending[1]<=now or message['stamp']<=self.peer_stamp.get(message['peer'],0):
            self.stats['rejected']+=1;return False
        flow=pending[0];peer=message['peer']
        if peer not in self.peer_stamp and len(self.peer_stamp)>=4096:
            self.stats['rejected']+=1;return False
        moved=[f for f,v in self.leases.items() if v[0]==peer and f!=flow]
        for old in moved:del self.leases[old]
        self.stats['moves']+=len(moved)
        self.peer_stamp[peer]=message['stamp'];self.leases[flow]=(peer,now+LEASE_SECONDS)
        self.history.append({'time_ns':int(now*1e9),'wall_ns':time.time_ns(),'flow':dataclasses.asdict(flow),'peer':peer,'replaced':[dataclasses.asdict(f) for f in moved]})
        self.history=self.history[-256:]
        self.stats['grants']+=1;return True

class Exit:
    def __init__(self,entry):
        self.entry=ipaddress.IPv4Address(entry).packed;self.pending={};self.stats={'queries':0,'proofs':0,'events':0,'rejected':0}
    def query(self,message,now,cutoff_ns=None):
        self.pending={n:v for n,v in self.pending.items() if v[2]>now}
        if set(message)!={'nonce','port'} or not nonce(message['nonce']) or type(message['port']) is not int or not 1<=message['port']<=65535 or message['nonce'] in self.pending or len(self.pending)>=MAX_PENDING:
            self.stats['rejected']+=1;return
        self.pending[message['nonce']]=(message['port'],int(now*1e9) if cutoff_ns is None else cutoff_ns,now+3);self.stats['queries']+=1
    def event(self,data,now):
        self.stats['events']+=1
        if len(data)!=EVENT.size:self.stats['rejected']+=1;return []
        magic,stamp,address,port,peer,counter=EVENT.unpack(data)
        if magic!=b'CWP1' or address!=self.entry or stamp>int(now*1e9) or int(now*1e9)-stamp>10**9:
            self.stats['rejected']+=1;return []
        messages=[]
        for request,(expected,cutoff,deadline) in list(self.pending.items()):
            if deadline<=now:del self.pending[request]
            elif expected==port and stamp>cutoff:
                messages.append({'nonce':request,'peer':peer.hex(),'stamp':stamp});del self.pending[request];self.stats['proofs']+=1
        return messages

class Stream:
    def __init__(self,connection):
        connection.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
        self.socket=connection;self.incoming=bytearray();self.outgoing=bytearray();connection.setblocking(False)
    def queue(self,message):
        data=json.dumps(message,separators=(',',':'),sort_keys=True).encode()+b'\n'
        assert len(data)<=512 and len(self.outgoing)+len(data)<=65536
        self.outgoing.extend(data)
    def read(self):
        messages=[]
        for _ in range(32):
            try:data=self.socket.recv(4096)
            except (ssl.SSLWantReadError,ssl.SSLWantWriteError):break
            if not data:raise EOFError
            self.incoming.extend(data);assert len(self.incoming)<=8192
            while b'\n' in self.incoming:
                line,_,rest=self.incoming.partition(b'\n');self.incoming=bytearray(rest)
                assert 0<len(line)<=512
                message=json.loads(line);assert isinstance(message,dict);messages.append(message)
            assert len(self.incoming)<=512 and len(messages)<=256
        return messages
    def write(self):
        if self.outgoing:
            try:sent=self.socket.send(self.outgoing)
            except (ssl.SSLWantReadError,ssl.SSLWantWriteError):return
            if sent<=0:raise EOFError
            del self.outgoing[:sent]

def private_file(path):
    value=Path(path);info=value.lstat()
    assert stat.S_ISREG(info.st_mode) and info.st_uid==0 and not info.st_mode&0o077
    return value

def context(config,role):
    private_file(config['key'])
    ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT if role=='entry' else ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version=ssl.TLSVersion.TLSv1_3
    ctx.load_cert_chain(config['cert'],config['key']);ctx.load_verify_locations(config['ca']);ctx.verify_mode=ssl.CERT_REQUIRED
    return ctx

def install_leases(state,flows,now):
    state.leases={f:v for f,v in state.leases.items() if f in flows and v[1]>now}
    command=f'flush set ip {TABLE} trusted\n'
    elements=[f'{f.source} . {f.port} . {f.identity} timeout {max(1,int((v[1]-now)*1000))}ms' for f,v in state.leases.items()]
    if elements:command+=f'add element ip {TABLE} trusted {{ '+', '.join(elements)+' }\n'
    subprocess.run(['nft','-f','-'],input=command,text=True,capture_output=True,timeout=2,check=True)

def snapshot(path,state,**values):
    value={'time_ns':time.monotonic_ns(),'stats':state.stats,**values}
    target=Path(path);temporary=target.with_suffix('.tmp');temporary.write_text(json.dumps(value)+'\n');temporary.replace(target)

def serve(config,role):
    assert os.geteuid()==0 and Path('/etc/hostname').read_text().strip()=='kit-'+role
    for name in ('entry','exit'):assert ipaddress.IPv4Address(config[name]).is_private
    assert type(config['vpn_port']) is int and 1<=config['vpn_port']<=65535
    ctx=context(config,role);alive=True
    def stop(*_):
        nonlocal alive
        alive=False
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    stream=None;last_status=0;next_tick=0
    if role=='exit':
        state=Exit(config['entry']);listener=socket.socket();listener.bind((config['exit'],39101));listener.listen(4);listener.setblocking(False)
        path=Path(config['events']);assert path.parent.stat().st_uid==0 and stat.S_IMODE(path.parent.stat().st_mode)==0o700
        if path.exists():assert stat.S_ISSOCK(path.lstat().st_mode) and path.lstat().st_uid==0;path.unlink()
        events=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM);events.setsockopt(socket.SOL_SOCKET,socket.SO_PASSCRED,1);events.bind(str(path));path.chmod(0o600)
    else:state=Entry();flows=set();next_connect=0;last_lease_shape=None
    try:
        while alive:
            now=time.monotonic()
            if role=='entry' and stream is None and now>=next_connect:
                try:
                    connection=socket.create_connection((config['exit'],39101),timeout=1,source_address=(config['entry'],0))
                    stream=Stream(ctx.wrap_socket(connection,server_hostname=config['exit']));state=Entry()
                except (OSError,ssl.SSLError):next_connect=now+1
            readers=([listener,events] if role=='exit' else [])+([stream.socket] if stream else [])
            writable=[stream.socket] if stream and stream.outgoing else []
            ready,writes,_=select.select(readers,writable,[],.05)
            lease_changed=False
            try:
                if role=='exit' and listener in ready:
                    connection,address=listener.accept()
                    if stream or address[0]!=config['entry']:connection.close()
                    else:
                        connection.settimeout(1)
                        try:stream=Stream(ctx.wrap_socket(connection,server_side=True));state=Exit(config['entry'])
                        except (OSError,ssl.SSLError):connection.close()
                if stream and stream.socket in ready:
                    for message in stream.read():
                        if role=='exit':state.query(message,time.monotonic(),time.monotonic_ns())
                        else:
                            flows=read_flows(config)
                            lease_changed=state.confirm(message,flows,time.monotonic()) or lease_changed
                if role=='exit' and events in ready:
                    data,ancillary,flags,_=events.recvmsg(256,socket.CMSG_SPACE(12))
                    trusted=any(level==socket.SOL_SOCKET and kind==socket.SCM_CREDENTIALS and struct.unpack('3i',value[:12])[1]==0 for level,kind,value in ancillary)
                    if trusted and not flags:
                        messages=state.event(data,time.monotonic())
                        if stream:
                            for message in messages:stream.queue(message)
                if stream and stream.socket in writes:stream.write()
            except (OSError,ssl.SSLError,EOFError,AssertionError,ValueError):
                if stream:stream.socket.close();stream=None
                if role=='entry':state=Entry();last_lease_shape=None;lease_changed=True
            now=time.monotonic()
            if role=='entry' and (now>=next_tick or lease_changed):
                if now>=next_tick:
                    try:flows=read_flows(config)
                    except (OSError,subprocess.SubprocessError,AssertionError):flows=set()
                    requests=state.queries(flows,now) if stream else []
                    for message in requests:stream.queue(message)
                    next_tick=now+POLL_SECONDS
                shape=tuple(sorted((f.source,f.port,f.identity,v[0],v[1]) for f,v in state.leases.items()))
                if shape!=last_lease_shape:
                    install_leases(state,flows,now);last_lease_shape=shape
            if now-last_status>=.5:
                values={'connected':stream is not None,'pending':len(state.pending)}
                if role=='entry':
                    values['leases']=[dataclasses.asdict(f)|{'peer':v[0],'expires_in':max(0,v[1]-now)} for f,v in state.leases.items()]
                    values['history']=state.history
                snapshot(config['status'],state,**values);last_status=now
    finally:
        if stream:stream.socket.close()
        if role=='entry':state.leases.clear();install_leases(state,set(),time.monotonic())
        else:listener.close();events.close();path.unlink(missing_ok=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--vm-test',action='store_true',required=True);parser.add_argument('role',choices=['entry','exit']);parser.add_argument('config',type=Path);args=parser.parse_args()
    config=json.loads(private_file(args.config).read_text());serve(config,args.role)
