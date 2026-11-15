#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Lab-only iperf sequence capture: decode actual GSO segments, discard bodies."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import socket
import struct
import subprocess
import sys

MAGIC=b'CWSEQ30\0'
HEADER=struct.Struct('<8sI')
RECORD=struct.Struct('<QI')

def read_exact(stream,size,eof=False):
    result=bytearray()
    while len(result)<size:
        value=stream.read(size-len(result))
        if not value:
            if eof and not result:return None
            raise ValueError('Truncated capture')
        result.extend(value)
    return bytes(result)

def extract(frame,link,payload):
    if link==1:
        if len(frame)<14 or frame[12:14]!=b'\x08\x00':return []
        frame=frame[14:]
    if len(frame)<28 or frame[0]>>4!=4 or frame[9]!=17:return []
    if struct.unpack_from('!H',frame,6)[0]&0x3fff:raise ValueError('Fragmented UDP needs reassembly; choose a payload below the lab MTU')
    ihl=(frame[0]&15)*4
    if ihl<20 or len(frame)<ihl+8:raise ValueError('Short IP/UDP header')
    sport,dport,_=struct.unpack_from('!HHH',frame,ihl)
    if 5201 not in (sport,dport):return []
    total=struct.unpack_from('!H',frame,2)[0];length=total-ihl-8
    if total>len(frame) or length<0:raise ValueError('Truncated IP datagram')
    if length<payload:return []
    tail=length%payload
    if tail and (tail!=4 or frame[ihl+8+length-4:ihl+8+length] not in (b'6789',b'9876')):raise ValueError('Unexpected iperf control suffix')
    values=[]
    for start in range(0,length-tail,payload):
        value=struct.unpack_from('!I',frame,ihl+16+start)[0]
        if not 0<value<=8_000_000:raise ValueError('Invalid iperf sequence')
        values.append(value)
    return values

def compact(stream,output,payload):
    if payload not in (128,512,1200):raise ValueError('Unsupported payload')
    header=read_exact(stream,24)
    if header[:4]!=b'\xd4\xc3\xb2\xa1':raise ValueError('Expected little-endian microsecond pcap')
    link=struct.unpack_from('<I',header,20)[0]
    if link not in (1,12,101):raise ValueError('Unsupported capture link')
    digest=hashlib.sha256(header);packets=0;count=0;maximum=0
    output.write(HEADER.pack(MAGIC,payload))
    while (record:=read_exact(stream,16,eof=True)) is not None:
        sec,usec,size,original=struct.unpack('<IIII',record)
        if not 0<size==original<=262144 or usec>=1_000_000:raise ValueError('Invalid/truncated pcap record')
        frame=read_exact(stream,size);digest.update(record);digest.update(frame);packets+=1
        values=extract(frame,link,payload);maximum=max(maximum,len(values))
        for value in values:output.write(RECORD.pack(sec*1_000_000_000+usec*1000,value));count+=1
    output.flush()
    return {'pcap_packets':packets,'actual_datagram_records':count,'maximum_GSO_segments':maximum,'pcap_stream_SHA256':digest.hexdigest(),'payload_bytes':payload,'complete':True}

def sequences(raw):
    if len(raw)<HEADER.size:raise ValueError('Short sequence capture')
    magic,payload=HEADER.unpack_from(raw)
    if magic!=MAGIC or payload not in (128,512,1200) or (len(raw)-HEADER.size)%RECORD.size:raise ValueError('Invalid sequence capture')
    result={};duplicates=0
    for stamp,number in RECORD.iter_unpack(raw[HEADER.size:]):
        if not stamp or not 0<number<=8_000_000:raise ValueError('Invalid sequence record')
        duplicates+=number in result;result[number]=stamp
    return result,duplicates

def self_test():
    for payload in (128,512,1200):
        header=struct.pack('<IHHIIII',0xa1b2c3d4,2,4,0,0,262144,101)
        ip=bytearray(28+2*payload);ip[0]=0x45;ip[9]=17
        struct.pack_into('!H',ip,2,len(ip));struct.pack_into('!HHH',ip,20,50000,5201,8+2*payload)
        struct.pack_into('!I',ip,36,1);struct.pack_into('!I',ip,36+payload,3)
        raw=header+struct.pack('<IIII',10,12,len(ip),len(ip))+ip
        output=io.BytesIO();meta=compact(io.BytesIO(raw),output,payload)
        values,duplicates=sequences(output.getvalue())
        assert set(values)=={1,3} and not duplicates and values[1]==10_000_012_000
        assert meta['actual_datagram_records']==2 and meta['maximum_GSO_segments']==2
        assert meta['pcap_stream_SHA256']==hashlib.sha256(raw).hexdigest()
        for bad in (raw[:-1],raw[:25],b'bad'):
            try:compact(io.BytesIO(bad),io.BytesIO(),payload)
            except ValueError:pass
            else:raise AssertionError('Truncated stream accepted')
        struct.pack_into('!H',ip,6,0x2000)
        try:extract(ip,101,payload)
        except ValueError:pass
        else:raise AssertionError('Fragmented data silently counted')
    print('PASS actual GSO counters with gaps, payloads128/512/1200, timestamps, truncation and fragment rejection')

def capture(interface,payload,target):
    if os.geteuid()!=0 or socket.gethostname() not in ('kit-client','kit-exit'):raise ValueError('Disposable VM only')
    if interface not in ('pf1','awg0'):raise ValueError('Unsupported lab interface')
    target=target.resolve();root=Path('/root/prefilter/pingtrace').resolve()
    if root not in target.parents:raise ValueError('Capture path outside lab directory')
    # Immediate mode allocates slots from snaplen; IPv4 needs 65535, not 262144.
    child=subprocess.Popen(['tcpdump','--immediate-mode','-nn','-i',interface,'-s','65535','-U','-B','65536','-Z','root','-w','-','udp port 5201'],stdout=subprocess.PIPE,stderr=sys.stderr)
    def stop(*_):
        if child.poll() is None:
            try:child.send_signal(signal.SIGTERM)
            except ProcessLookupError:pass
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:
        with target.open('xb') as output:meta=compact(child.stdout,output,payload)
        status=child.wait(timeout=3)
        if status not in (0,-signal.SIGTERM,-signal.SIGINT):raise RuntimeError('tcpdump failed: '+str(status))
        meta['tcpdump_exit_status']=status
        target.with_suffix(target.suffix+'.meta.json').write_text(json.dumps(meta)+'\n')
    finally:
        if child.poll() is None:child.kill();child.wait()

if __name__=='__main__':
    if sys.argv[1:]==['--self-test']:self_test()
    else:
        parser=argparse.ArgumentParser();parser.add_argument('interface',choices=('pf1','awg0'));parser.add_argument('payload',type=int,choices=(128,512,1200));parser.add_argument('output',type=Path);args=parser.parse_args()
        capture(args.interface,args.payload,args.output)
