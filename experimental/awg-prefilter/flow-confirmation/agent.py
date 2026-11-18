#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Disposable IPv4 lab: short conntrack leases after exit-authenticated data."""
import argparse
import dataclasses
import errno
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import secrets
import select
import signal
import socket
import ssl
import stat
import struct
import subprocess
import time
import conntrack

TABLE='awg_kernel_guard_lab'
LATE_TABLE='awg_escrow_bridge_lab'
LEASE_SECONDS=10
MAX_PENDING=128
RECOVERY_SECONDS=1
PEER_FLOWS=4
POLL_SECONDS=.1
EVENT=struct.Struct('!4sQ4sH16sQ')
ESCROW_RECORD=struct.Struct('!4sHIQ')
ESCROW_SOCKET='/run/coldwire-escrow/grants.sock'
CANDIDATE=struct.Struct('!4s4sHI')

@dataclasses.dataclass(frozen=True)
class Flow:
    source: str
    port: int
    identity: int
    translated_port: int

def read_flow(config,port):
    value=conntrack.lookup(config['entry'],config['exit'],config['vpn_port'],port)
    return Flow(*value) if value else None

def nonce(value):
    return isinstance(value,str) and len(value)==32 and all(c in '0123456789abcdef' for c in value)

class Entry:
    def __init__(self,escrow_socket=None,late_escrow=False):
        assert type(late_escrow) is bool and (not late_escrow or escrow_socket==ESCROW_SOCKET)
        self.escrow_socket=escrow_socket
        self.late_escrow=late_escrow
        self.flows={};self.observed={};self.looked_up={};self.auth_hints={};self.last_escrow=0
        self.ready=set();self.probed=set();self.sent=set();self.early_probed=set()
        self.pending={};self.leases={};self.last_query={};self.peer_stamp={};self.history=[];self.stats={'queries':0,'grants':0,'rejected':0,'moves':0}
    def new_control_session(self):
        # Fresh nonces bind proofs to this authenticated session; B's clock may have restarted.
        self.pending.clear();self.ready.clear();self.probed.clear();self.sent.clear();self.early_probed.clear();self.peer_stamp.clear()
    def control_timed_out(self,now):
        return any(deadline<=now and request not in self.ready for request,(_,deadline) in self.pending.items())
    def _observe(self,port,now):
        if port not in self.observed and len(self.observed)>=MAX_PENDING:
            protected=set(self.leases)|{v[0] for v in self.pending.values()}|{f for f,t in self.auth_hints.items() if t>now}
            available=[p for p in self.observed if self.flows.get(p) not in protected]
            if not available:self.stats['rejected']+=1;return False
            old=min(available,key=lambda p:self.observed[p]);stale=self.flows.pop(old,None);self.auth_hints.pop(stale,None);self.observed.pop(old);self.looked_up.pop(old,None)
        self.observed[port]=now
        return True
    def _remember(self,flow,now,authenticated):
        port=flow.translated_port;previous=self.flows.get(port)
        if previous!=flow:self.auth_hints.pop(previous,None)
        self.flows[port]=flow;self.looked_up[port]=now
        if authenticated:self.auth_hints[flow]=now+3
    def hint(self,message,config,now,authenticated=True):
        if set(message)!={'hint'} or type(message['hint']) is not int or not 1<=message['hint']<=65535:
            self.stats['rejected']+=1;return False
        port=message['hint']
        if not self._observe(port,now):return False
        if now-self.looked_up.get(port,-10)<.5:
            if authenticated and port in self.flows:
                flow=self.flows[port];changed=self.auth_hints.get(flow,0)<=now
                self.auth_hints[flow]=now+3
                return changed
            return False
        self.looked_up[port]=now
        try:flow=read_flow(config,port)
        except (OSError,ValueError):
            self.stats['lookup_failed']=self.stats.get('lookup_failed',0)+1;return False
        if flow:self._remember(flow,now,authenticated)
        else:self.auth_hints.pop(self.flows.pop(port,None),None)
        if not flow:self.observed.pop(port,None);self.looked_up.pop(port,None)
        return flow is not None
    def current_flows(self,config,now):
        # C announces a holding flow once; recheck its generation after a control outage.
        stale=[p for p in self.observed if now-self.observed[p]>=LEASE_SECONDS]
        for port in stale[:16]:
            previous=self.flows.get(port)
            try:current=read_flow(config,port) if previous else None
            except (OSError,ValueError):
                self.stats['lookup_failed']=self.stats.get('lookup_failed',0)+1;current=None
            if previous is not None and current==previous:
                self.observed[port]=now;self.looked_up[port]=now
            else:
                self.auth_hints.pop(self.flows.pop(port,None),None);self.observed.pop(port);self.looked_up.pop(port,None)
        return {f for p,f in self.flows.items() if now-self.observed[p]<LEASE_SECONDS}
    def candidate(self,data,config,now):
        if len(data)!=CANDIDATE.size:return False
        magic,address,port,identity=CANDIDATE.unpack(data)
        if magic!=b'CWC1' or not port or not identity:return False
        source=str(ipaddress.IPv4Address(address))
        priority={f for f,(_,until) in self.leases.items() if until>now}|{f for f,until in self.auth_hints.items() if until>now}
        same=[f for f in self.flows.values() if f.source==source]
        if sum(f not in priority for f in same)>=4 and not any(f.port==port and f.identity==identity for f in same):
            self.stats['candidate_source_limited']=self.stats.get('candidate_source_limited',0)+1;return False
        try:
            value=conntrack.lookup(config['entry'],config['exit'],config['vpn_port'],None,original=(source,port),identity=identity)
        except (OSError,ValueError):return False
        if not value:return False
        flow=Flow(*value)
        if flow not in priority and sum(f.source==flow.source and f not in priority for p,f in self.flows.items() if p!=flow.translated_port)>=4:
            self.stats['candidate_source_limited']=self.stats.get('candidate_source_limited',0)+1;return False
        if not self._observe(flow.translated_port,now):return False
        # Preserve the original-tuple/generation check instead of resolving the reply port again.
        self._remember(flow,now,authenticated=False)
        return True
    def queries(self,flows,now):
        self.pending={n:v for n,v in self.pending.items() if v[0] in flows and v[1]>now}
        self.ready.intersection_update(self.pending);self.probed.intersection_update(self.pending);self.sent.intersection_update(self.pending);self.early_probed.intersection_update(self.pending)
        self.leases={f:v for f,v in self.leases.items() if f in flows and v[1]>now}
        self.last_query={f:t for f,t in self.last_query.items() if f in flows}
        self.auth_hints={f:t for f,t in self.auth_hints.items() if f in flows and t>now}
        busy={v[0] for v in self.pending.values()}
        priority=set(self.leases)|set(self.auth_hints)
        unknown=[v[0] for v in self.pending.values() if v[0] not in priority]
        source_pending={f.source:sum(v.source==f.source for v in unknown) for f in unknown}
        candidates=sorted(flows,key=lambda f:(f not in priority,self.last_query.get(f,-1),f.source,f.port))
        result=[]
        for flow in candidates:
            if flow in busy or now-self.last_query.get(flow,-10)<1 or len(self.pending)>=MAX_PENDING:continue
            # Reserve challenges for authenticated hints/renewals; one IP cannot occupy all unknown slots.
            if flow not in priority and (len(unknown)>=MAX_PENDING-16 or source_pending.get(flow.source,0)>=4):continue
            if flow in self.leases and self.leases[flow][1]-now>LEASE_SECONDS-2:continue
            request=secrets.token_hex(16)
            self.pending[request]=(flow,now+3);self.last_query[flow]=now
            result.append({'nonce':request,'port':flow.translated_port});self.stats['queries']+=1
            if flow not in priority:unknown.append(flow);source_pending[flow.source]=source_pending.get(flow.source,0)+1
            if len(result)==16:break
        return result
    def acknowledged(self,message,now):
        if set(message)!={'ready'} or not nonce(message['ready']):return False
        pending=self.pending.get(message['ready'])
        if not pending or pending[1]<=now:return False
        self.ready.add(message['ready']);return True
    def probes(self,flows,now):
        # Every probe stays untrusted until B authenticates a fresh transport packet.
        return [(n,f) for n,(f,deadline) in self.pending.items()
                if self.escrow_socket and ((n in self.ready and n not in self.probed) or (n in self.sent and n not in self.ready and n not in self.early_probed))
                and deadline>now and f in flows
                and (f not in self.leases or self.leases[f][1]<=now)]
    def confirm(self,message,flows,now):
        if set(message) not in ({'nonce','peer','stamp'},{'nonce','peer','stamp','recovery'}) or type(message.get('recovery',False)) is not bool or not nonce(message['nonce']) or not nonce(message['peer']) or type(message['stamp']) is not int or message['stamp']<=0:
            self.stats['rejected']+=1;return False
        pending=self.pending.pop(message['nonce'],None)
        if not pending or pending[0] not in flows or pending[1]<=now or message['stamp']<=self.peer_stamp.get(message['peer'],0):
            self.stats['rejected']+=1;return False
        flow=pending[0];peer=message['peer']
        if peer not in self.peer_stamp and len(self.peer_stamp)>=4096:
            self.stats['rejected']+=1;return False
        moved=[f for f,v in self.leases.items() if v[0]==peer and f!=flow]
        for old in moved:
            if not message.get('recovery'):self.leases[old]=(peer,min(self.leases[old][1],now+RECOVERY_SECONDS))
        if not message.get('recovery') and flow not in self.leases:self.stats['moves']+=bool(moved)
        until=now+(RECOVERY_SECONDS if message.get('recovery') else LEASE_SECONDS)
        if flow in self.leases and self.leases[flow][0]==peer:until=max(until,self.leases[flow][1])
        self.peer_stamp[peer]=message['stamp'];self.leases[flow]=(peer,until)
        evicted=sorted(moved,key=lambda f:self.leases[f][1])[:max(0,len(moved)+1-PEER_FLOWS)]
        for old in evicted:del self.leases[old]
        self.history.append({'time_ns':int(now*1e9),'wall_ns':time.time_ns(),'flow':dataclasses.asdict(flow),'peer':peer,'recovery':message.get('recovery',False),'replaced':[dataclasses.asdict(f) for f in evicted]})
        self.history=self.history[-256:]
        self.stats['grants']+=1;return True

class Exit:
    def __init__(self,entry):
        self.entry=ipaddress.IPv4Address(entry).packed;self.pending={};self.hinted={};self.hint_tokens=16;self.hint_time=0;self.stats={'queries':0,'proofs':0,'events':0,'rejected':0,'hints':0}
    def query(self,message,now,cutoff_ns=None):
        self.pending={n:v for n,v in self.pending.items() if v[2]>now}
        if set(message)!={'nonce','port'} or not nonce(message['nonce']) or type(message['port']) is not int or not 1<=message['port']<=65535 or message['nonce'] in self.pending or len(self.pending)>=MAX_PENDING:
            self.stats['rejected']+=1;return
        self.pending[message['nonce']]=(message['port'],int(now*1e9) if cutoff_ns is None else cutoff_ns,now+3);self.stats['queries']+=1
        return True
    def event(self,data,now):
        self.stats['events']+=1
        if len(data)!=EVENT.size:self.stats['rejected']+=1;return []
        magic,stamp,address,port,peer,counter=EVENT.unpack(data)
        if magic not in (b'CWP1',b'CWA1') or address!=self.entry or not port or stamp>int(now*1e9) or int(now*1e9)-stamp>10**9:
            self.stats['rejected']+=1;return []
        messages=[]
        self.hint_tokens=min(16,self.hint_tokens+max(0,now-self.hint_time)*64);self.hint_time=now
        if now-self.hinted.get(port,-10)>=.25 and self.hint_tokens>=1:
            if port not in self.hinted and len(self.hinted)>=MAX_PENDING:del self.hinted[min(self.hinted,key=self.hinted.get)]
            self.hinted[port]=now;self.hint_tokens-=1;messages.append({'hint':port});self.stats['hints']+=1
        for request,(expected,cutoff,deadline) in list(self.pending.items()):
            if deadline<=now:del self.pending[request]
            elif expected==port and stamp>cutoff:
                proof={'nonce':request,'peer':peer.hex(),'stamp':stamp}
                if magic==b'CWA1':proof['recovery']=True
                messages.append(proof);del self.pending[request];self.stats['proofs']+=1
        return messages

class Handshake:
    def __init__(self,connection,deadline,connecting=False):
        self.socket=connection;self.deadline=deadline;self.connecting=connecting;self.write=connecting
    @classmethod
    def outgoing(cls,ctx,config,now):
        connection=socket.socket()
        try:
            connection.setblocking(False);connection.bind((config['entry'],0))
            connection=ctx.wrap_socket(connection,server_hostname=config['exit'],do_handshake_on_connect=False)
            result=connection.connect_ex((config['exit'],39101))
            if result not in (0,errno.EINPROGRESS,errno.EWOULDBLOCK,errno.EALREADY):raise OSError(result,'Control connect failed')
            value=cls(connection,now+2,connecting=result!=0);value.write=True
            return value
        except BaseException:
            connection.close();raise
    @classmethod
    def incoming(cls,ctx,connection,now):
        try:
            connection.setblocking(False)
            connection=ctx.wrap_socket(connection,server_side=True,do_handshake_on_connect=False)
            return cls(connection,now+1)
        except BaseException:
            connection.close();raise
    def advance(self,now):
        if now>=self.deadline:raise TimeoutError('Control handshake deadline expired')
        if self.connecting:
            error=self.socket.getsockopt(socket.SOL_SOCKET,socket.SO_ERROR)
            if error:raise OSError(error,'Control connect failed')
            self.connecting=False
        try:self.socket.do_handshake()
        except ssl.SSLWantReadError:self.write=False;return False
        except ssl.SSLWantWriteError:self.write=True;return False
        return True

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
    command=''
    elements=[f'{f.source} . {f.port} . {f.identity} timeout {max(1,int((v[1]-now)*1000))}ms' for f,v in state.leases.items()]
    for family,table in [('ip',TABLE)]+([('bridge',LATE_TABLE)] if state.late_escrow else []):
        command+=f'flush set {family} {table} trusted\n'
        if elements:command+=f'add element {family} {table} trusted {{ '+', '.join(elements)+' }\n'
    subprocess.run(['nft','-f','-'],input=command,text=True,capture_output=True,timeout=2,check=True)
    if state.escrow_socket:sync_escrow(state,now)

def sync_escrow(state,now):
    state.last_escrow=now
    if not notify_escrow(state):state.stats['escrow_notify_failed']=state.stats.get('escrow_notify_failed',0)+1

def probe_escrow(state,flow,now,early=False):
    try:
        if state.escrow_socket!=ESCROW_SOCKET or type(early) is not bool:return False
        parent=Path(ESCROW_SOCKET).parent.lstat();info=Path(ESCROW_SOCKET).lstat()
        if not stat.S_ISDIR(parent.st_mode) or parent.st_uid or stat.S_IMODE(parent.st_mode)!=0o700 or not stat.S_ISSOCK(info.st_mode) or info.st_uid or stat.S_IMODE(info.st_mode)!=0o600:return False
        data=(b'CWT1' if early else b'CWS1')+ESCROW_RECORD.pack(ipaddress.IPv4Address(flow.source).packed,flow.port,flow.identity,int((now+RECOVERY_SECONDS)*1e9))
        with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as connection:
            connection.setblocking(False);return connection.sendto(data,ESCROW_SOCKET)==len(data)
    except (OSError,ValueError,struct.error):return False

def notify_escrow(state,refresh=False):
    """Refreshes carry no grants; lease notifications stay within the kernel set."""
    try:
        assert state.escrow_socket==ESCROW_SOCKET and len(state.leases)<=MAX_PENDING and type(refresh) is bool
        path=Path(state.escrow_socket);parent=path.parent.lstat();info=path.lstat()
        assert stat.S_ISDIR(parent.st_mode) and parent.st_uid==0 and stat.S_IMODE(parent.st_mode)==0o700
        assert stat.S_ISSOCK(info.st_mode) and info.st_uid==0 and stat.S_IMODE(info.st_mode)==0o600
        data=b'CWR1' if refresh else struct.pack('!4sH',b'CWE1',len(state.leases))
        # Stop cached C grants one poll early; the kernel gate remains authoritative.
        if not refresh:data+=b''.join(ESCROW_RECORD.pack(ipaddress.IPv4Address(f.source).packed,f.port,f.identity,int((v[1]-POLL_SECONDS)*1e9)) for f,v in state.leases.items())
        with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as connection:
            connection.setblocking(False)
            return connection.sendto(data,str(path))==len(data)
    except (OSError,AssertionError,ValueError,struct.error):return False

def snapshot(path,state,**values):
    value={'time_ns':time.monotonic_ns(),'stats':state.stats,**values}
    target=Path(path);temporary=target.with_suffix('.tmp');temporary.write_text(json.dumps(value)+'\n');temporary.replace(target)

def entry_values(state,config,boot,now):
    return {'lease_boot':boot,'lease_context':[config['entry'],config['exit'],config['vpn_port'],state.late_escrow],
            'leases':[dataclasses.asdict(f)|{'peer':v[0],'expires_in':max(0,v[1]-now),'deadline_ns':int(v[1]*1e9)} for f,v in state.leases.items()],
            'candidates':[dataclasses.asdict(f)|{'observed_ns':int(state.observed[p]*1e9)} for p,f in state.flows.items() if p in state.observed and now-state.observed[p]<LEASE_SECONDS],
            'history':state.history}

def cached_flow(record):
    flow=Flow(*(record[k] for k in ('source','port','identity','translated_port')))
    assert str(ipaddress.IPv4Address(flow.source))==flow.source
    assert type(flow.port) is int and 1<=flow.port<=65535 and type(flow.translated_port) is int and 1<=flow.translated_port<=65535
    assert type(flow.identity) is int and 1<=flow.identity<=0xffffffff
    return flow

def restore_leases(state,config,boot):
    """A cache can only shorten a live kernel lease of the same conntrack generation."""
    try:
        path=private_file(config['status']);assert path.stat().st_size<=262144
        saved=json.loads(path.read_text());now_ns=time.monotonic_ns()
        assert saved['lease_boot']==boot and saved['lease_context']==[config['entry'],config['exit'],config['vpn_port'],state.late_escrow]
        stamp=saved['time_ns'];assert type(stamp) is int and 0<=now_ns-stamp<=LEASE_SECONDS*10**9
        records=saved['leases'];assert isinstance(records,list) and len(records)<=MAX_PENDING
        live=[]
        for family,table in [('ip',TABLE)]+([('bridge',LATE_TABLE)] if state.late_escrow else []):
            before=time.monotonic_ns()
            result=subprocess.run(['nft','-j','list','set',family,table,'trusted'],text=True,capture_output=True,timeout=2,check=True)
            sets=[x['set'] for x in json.loads(result.stdout)['nftables'] if 'set' in x]
            assert len(sets)==1 and sets[0]['family']==family and sets[0]['table']==table and sets[0]['name']=='trusted'
            elements=sets[0].get('elem',[]);assert isinstance(elements,list) and len(elements)<=4096
            deadlines={}
            for item in elements:
                element=item['elem'];source,port,identity=element['val']['concat'];remaining=element['expires']
                assert str(ipaddress.IPv4Address(source))==source and type(port) is int and 1<=port<=65535
                assert type(identity) is int and 1<=identity<=0xffffffff and type(remaining) is int and 0<=remaining<=LEASE_SECONDS
                key=(source,port,identity);assert key not in deadlines
                # nft JSON reports whole seconds, rounded down; time before GET is conservative.
                deadlines[key]=before+remaining*10**9
            live.append(deadlines)
        restored={};peers={}
        for record in records:
            flow=cached_flow(record)
            assert nonce(record['peer']) and flow not in restored
            deadline=record['deadline_ns'];assert type(deadline) is int and deadline<=stamp+LEASE_SECONDS*10**9
            key=(flow.source,flow.port,flow.identity)
            deadline=min([deadline]+[values.get(key,0) for values in live])
            if deadline<=time.monotonic_ns() or read_flow(config,flow.translated_port)!=flow:continue
            peer=record['peer'];peers[peer]=peers.get(peer,0)+1;assert peers[peer]<=PEER_FLOWS
            restored[flow]=(peer,deadline/1e9)
        records=saved.get('candidates',[]);assert isinstance(records,list) and len(records)<=MAX_PENDING
        observed={};ports=set()
        for record in records:
            flow=cached_flow(record);seen=record['observed_ns']
            assert type(seen) is int and seen<=stamp and flow.translated_port not in ports
            ports.add(flow.translated_port)
            if now_ns-seen>=LEASE_SECONDS*10**9 or flow in restored:continue
            if read_flow(config,flow.translated_port)==flow:observed[flow]=seen/1e9
        assert len(restored)+len(observed)<=MAX_PENDING
    except FileNotFoundError:return 0
    except (OSError,ValueError,AssertionError,KeyError,TypeError,OverflowError,subprocess.SubprocessError):
        state.stats['restore_rejected']=state.stats.get('restore_rejected',0)+1;return 0
    now=time.monotonic()
    for flow in restored:
        state._observe(flow.translated_port,now);state._remember(flow,now,False)
    state.leases.update(restored);state.stats['restored_leases']=len(restored)
    for flow,seen in observed.items():
        state._observe(flow.translated_port,seen);state._remember(flow,now,False)
    state.stats['restored_candidates']=len(observed)
    return len(restored)

def serve(config,role):
    assert os.geteuid()==0 and Path('/etc/hostname').read_text().strip()=='kit-'+role
    for name in ('entry','exit'):assert ipaddress.IPv4Address(config[name]).is_private
    assert type(config['vpn_port']) is int and 1<=config['vpn_port']<=65535
    escrow_socket=config.get('escrow_socket') if role=='entry' else None
    assert escrow_socket in (None,ESCROW_SOCKET)
    ctx=context(config,role);alive=True
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip() if role=='entry' else None
    def stop(*_):
        nonlocal alive
        alive=False
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    stream=None;handshake=None;last_status=0;next_tick=0;candidates=None;candidate_path=None
    if role=='exit':
        state=Exit(config['entry']);listener=socket.socket();listener.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);listener.bind((config['exit'],39101));listener.listen(4);listener.setblocking(False)
        path=Path(config['events']);assert path.parent.stat().st_uid==0 and stat.S_IMODE(path.parent.stat().st_mode)==0o700
        if path.exists():assert stat.S_ISSOCK(path.lstat().st_mode) and path.lstat().st_uid==0;path.unlink()
        events=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM);events.setsockopt(socket.SOL_SOCKET,socket.SO_PASSCRED,1);events.bind(str(path));path.chmod(0o600)
    else:
        state=Entry(escrow_socket,config.get('late_escrow',False));flows=set();next_connect=0;last_lease_shape=None
        if escrow_socket:
            candidate_path=Path(escrow_socket).with_name('candidates.sock')
            parent=candidate_path.parent.lstat();assert stat.S_ISDIR(parent.st_mode) and parent.st_uid==0 and stat.S_IMODE(parent.st_mode)==0o700
            candidates=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM);candidates.setblocking(False);candidates.setsockopt(socket.SOL_SOCKET,socket.SO_PASSCRED,1)
            if candidate_path.exists():
                info=candidate_path.lstat();assert stat.S_ISSOCK(info.st_mode) and info.st_uid==0 and stat.S_IMODE(info.st_mode)==0o600
                with socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM) as probe:
                    try:probe.connect(str(candidate_path))
                    except ConnectionRefusedError:candidate_path.unlink()
                    else:raise OSError('Candidate helper is already running')
            candidates.bind(str(candidate_path));candidate_path.chmod(0o600)
        restore_leases(state,config,boot)
        refresh_pending=bool(candidates);refresh_deadline=time.monotonic()+2
    try:
        while alive:
            now=time.monotonic()
            if role=='entry' and stream is None and handshake is None and now>=next_connect:
                try:
                    handshake=Handshake.outgoing(ctx,config,now)
                except (OSError,ssl.SSLError):next_connect=now+1
            readers=([listener,events] if role=='exit' else [])+([stream.socket] if stream else [])
            if candidates:readers.append(candidates)
            writable=[stream.socket] if stream and stream.outgoing else []
            if handshake:(writable if handshake.write else readers).append(handshake.socket)
            timeout=.05
            if role=='entry':
                timeout=min(timeout,max(0,next_tick-now))
            ready,writes,_=select.select(readers,writable,[],timeout)
            lease_changed=False;established=False
            try:
                if candidates and candidates in ready:
                    for _ in range(64):
                        try:data,ancillary,flags,_=candidates.recvmsg(256,socket.CMSG_SPACE(12))
                        except BlockingIOError:break
                        trusted=any(level==socket.SOL_SOCKET and kind==socket.SCM_CREDENTIALS and len(value)>=12 and struct.unpack('3i',value[:12])[1]==0 for level,kind,value in ancillary)
                        if trusted and not flags and state.candidate(data,config,time.monotonic()):next_tick=0
                if role=='exit' and listener in ready:
                    connection,address=listener.accept()
                    if address[0]!=config['entry'] or handshake:connection.close()
                    else:
                        try:handshake=Handshake.incoming(ctx,connection,time.monotonic())
                        except (OSError,ssl.SSLError):pass
                if handshake and (handshake.socket in ready or handshake.socket in writes or time.monotonic()>=handshake.deadline):
                    try:
                        if handshake.advance(time.monotonic()):
                            previous=stream;stream=Stream(handshake.socket);handshake=None;established=True
                            if role=='exit':state=Exit(config['entry'])
                            else:state.new_control_session();next_tick=0
                            if previous:previous.socket.close()
                    except (OSError,ssl.SSLError):
                        handshake.socket.close();handshake=None
                        if role=='entry':next_connect=time.monotonic()+.2
                if stream and (established or stream.socket in ready or stream.socket.pending()):
                    for message in stream.read():
                        if role=='exit':
                            if state.query(message,time.monotonic(),time.monotonic_ns()):stream.queue({'ready':message['nonce']})
                        else:
                            if 'hint' in message:
                                if state.hint(message,config,time.monotonic()):next_tick=0
                            elif 'ready' in message:
                                if state.acknowledged(message,time.monotonic()):next_tick=0
                            else:
                                request=message.get('nonce');pending=state.pending.get(request) if nonce(request) else None
                                fresh=set()
                                if pending:
                                    try:flow=read_flow(config,pending[0].translated_port)
                                    except (OSError,ValueError):flow=None
                                    if flow:fresh.add(flow)
                                lease_changed=state.confirm(message,fresh,time.monotonic()) or lease_changed
                            flows=state.current_flows(config,time.monotonic())
                if role=='exit' and events in ready:
                    data,ancillary,flags,_=events.recvmsg(256,socket.CMSG_SPACE(12))
                    trusted=any(level==socket.SOL_SOCKET and kind==socket.SCM_CREDENTIALS and struct.unpack('3i',value[:12])[1]==0 for level,kind,value in ancillary)
                    if trusted and not flags:
                        messages=state.event(data,time.monotonic())
                        if stream:
                            for message in messages:stream.queue(message)
                if stream and stream.socket in writes:
                    stream.write()
                    if role=='entry' and not stream.outgoing:state.sent.update(state.pending)
                if role=='entry' and stream and state.control_timed_out(time.monotonic()):
                    state.stats['control_timeouts']=state.stats.get('control_timeouts',0)+1
                    raise TimeoutError('Control acknowledgement deadline expired')
            except (OSError,ssl.SSLError,EOFError,AssertionError,ValueError):
                if stream:stream.socket.close();stream=None
                if role=='entry':
                    state.pending.clear();state.ready.clear();state.probed.clear();state.sent.clear();state.early_probed.clear();next_connect=time.monotonic()+.2
            now=time.monotonic()
            if role=='entry' and (now>=next_tick or lease_changed):
                if now>=next_tick:
                    if refresh_pending and now<refresh_deadline and notify_escrow(state,refresh=True):
                        refresh_pending=False;state.stats['candidate_refresh_sent']=state.stats.get('candidate_refresh_sent',0)+1
                    flows=state.current_flows(config,now)
                    if not stream:state.leases={f:v for f,v in state.leases.items() if f in flows and v[1]>now}
                    requests=state.queries(flows,now) if stream else []
                    for message in requests:stream.queue(message)
                    for request,flow in state.probes(flows,now):
                        try:current=read_flow(config,flow.translated_port)
                        except (OSError,ValueError):current=None
                        if current==flow:
                            early=request not in state.ready
                            delivered=probe_escrow(state,flow,now,early=True) if early else probe_escrow(state,flow,now)
                            if delivered:(state.early_probed if early else state.probed).add(request)
                    next_tick=now+POLL_SECONDS
                shape=tuple(sorted((f.source,f.port,f.identity,v[0],v[1]) for f,v in state.leases.items()))
                if shape!=last_lease_shape:
                    install_leases(state,flows,now);last_lease_shape=shape
                if state.escrow_socket and now-state.last_escrow>=.25:sync_escrow(state,now)
            if now-last_status>=.5:
                values={'connected':stream is not None,'pending':len(state.pending)}
                if role=='entry':
                    values.update(entry_values(state,config,boot,now))
                snapshot(config['status'],state,**values);last_status=now
    finally:
        if handshake:handshake.socket.close()
        if stream:stream.socket.close()
        if candidates:candidates.close();candidate_path.unlink(missing_ok=True)
        if role=='entry':
            if alive:state.leases.clear();install_leases(state,set(),time.monotonic())
            snapshot(config['status'],state,connected=False,pending=0,**entry_values(state,config,boot,time.monotonic()))
        else:listener.close();events.close();path.unlink(missing_ok=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--vm-test',action='store_true',required=True);parser.add_argument('role',choices=['entry','exit']);parser.add_argument('config',type=Path);args=parser.parse_args()
    config=json.loads(private_file(args.config).read_text());serve(config,args.role)
