"""Fixed IPv4 probe for disposable AWG lab namespaces; changes no networking."""
import json
import os
import secrets
import select
import socket
import struct
import sys
import time

TARGET='10.8.1.1'
COUNT=100
INTERVAL_NS=20000000
TIMEOUT_NS=1000000000


def checksum(data):
    if len(data)%2:data+=b'\0'
    total=sum(struct.unpack('!'+str(len(data)//2)+'H',data))
    while total>>16:total=(total&65535)+(total>>16)
    return (~total)&65535


def request(identifier,sequence,token,stamp):
    payload=token+struct.pack('!Q',stamp)+bytes(range(40))
    raw=struct.pack('!BBHHH',8,0,0,identifier,sequence)+payload
    return raw[:2]+struct.pack('!H',checksum(raw))+raw[4:]


def reply_sequence(raw,peer,identifier,token):
    if peer!=TARGET or len(raw)!=64 or checksum(raw)!=0:return None
    kind,code,_,received_id,sequence=struct.unpack_from('!BBHHH',raw)
    if kind!=0 or code!=0 or received_id!=identifier or raw[8:16]!=token:return None
    return sequence if 1<=sequence<=COUNT else None


def icmp_body(raw):
    if len(raw)<20 or raw[0]>>4!=4 or raw[9]!=1:return b''
    ihl=(raw[0]&15)*4;total=struct.unpack_from('!H',raw,2)[0]
    return raw[ihl:total] if 20<=ihl<=60 and ihl+8<=total<=len(raw) else b''


def probe():
    token=secrets.token_bytes(8);sent={};replies={};late={};duplicates=0
    with socket.socket(socket.AF_INET,socket.SOCK_RAW,socket.IPPROTO_ICMP) as sock:
        sock.setblocking(False)
        identifier=os.getpid()&65535
        next_send=time.monotonic_ns();end=None
        while True:
            now=time.monotonic_ns()
            if len(sent)<COUNT and now>=next_send:
                sequence=len(sent)+1;raw=request(identifier,sequence,token,now)
                assert sock.sendto(raw,(TARGET,0))==len(raw)
                sent[sequence]=now;next_send=now+INTERVAL_NS
                if len(sent)==COUNT:end=now+TIMEOUT_NS
            if len(replies)==COUNT or (end is not None and now>=end):break
            wake=next_send if len(sent)<COUNT else end
            ready,_,_=select.select([sock],[],[],max(0,(wake-time.monotonic_ns())/1e9))
            if not ready:continue
            while True:
                try:raw,peer=sock.recvfrom(65535)
                except BlockingIOError:break
                arrival=time.monotonic_ns();wall=time.time_ns()
                sequence=reply_sequence(icmp_body(raw),peer[0],identifier,token)
                if sequence not in sent:continue
                if sequence in replies or sequence in late:duplicates+=1;continue
                value={'sequence':sequence,'wall_ns':wall,'rtt_ms':(arrival-sent[sequence])/1e6}
                (replies if arrival-sent[sequence]<=TIMEOUT_NS else late)[sequence]=value
    assert len(sent)==COUNT
    return {'target':TARGET,'sent':len(sent),'received':len(replies),'missing_sequences':sorted(set(sent)-set(replies)),
            'timeout_ns':TIMEOUT_NS,'interval_ns':INTERVAL_NS,'identifier':identifier,
            'replies':list(replies.values()),'late_replies':list(late.values()),'duplicates':duplicates}


def self_test():
    token=b'12345678';raw=request(42,100,token,123)
    assert len(raw)==64 and checksum(raw)==0
    response=bytes([0])+raw[1:2]+b'\0\0'+raw[4:]
    response=response[:2]+struct.pack('!H',checksum(response))+response[4:]
    assert reply_sequence(response,TARGET,42,token)==100
    assert reply_sequence(response,TARGET,43,token) is None
    assert reply_sequence(response,'10.8.1.2',42,token) is None
    assert reply_sequence(response[:-1],TARGET,42,token) is None
    bad=bytearray(response);bad[-1]^=1
    assert reply_sequence(bytes(bad),TARGET,42,token) is None
    assert reply_sequence(raw,TARGET,42,token) is None
    ip=struct.pack('!BBHHHBBH4s4s',0x45,0,20+len(response),0,0,64,1,0,b'\0'*4,b'\0'*4)
    assert icmp_body(ip+response)==response
    assert not icmp_body(ip+response[:-1])
    print('PASS ICMP checksum, fixed packet length, target/id/token/type validation and last sequence')


if __name__=='__main__':
    if sys.argv[1:]==['--self-test']:self_test()
    else:
        assert sys.argv[1:]==['--vm-test'] and sys.platform=='linux' and os.geteuid()==0
        result=probe();print(json.dumps(result));raise SystemExit(0 if result['received']==COUNT else 1)
