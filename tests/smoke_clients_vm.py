#!/usr/bin/env python3
"""LAB ONLY: verify exported profiles from a separate disposable Debian/Ubuntu client VM."""
import argparse
import contextlib
import copy
import http.client
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import socket
import ssl
import struct
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('xray_probe', ROOT / 'servers/probe-xray.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def run(*args, data=None):
    p = subprocess.run(args, input=data, text=True, capture_output=True, timeout=90)
    if p.returncode:
        raise RuntimeError('Client lab command failed; private output suppressed: ' + args[0])
    return p.stdout.strip()


@contextlib.contextmanager
def proxy(binary, config):
    config = copy.deepcopy(config)
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]
    config['inbounds'][0]['port'] = port
    with tempfile.TemporaryDirectory(dir='/run', prefix='kit-client-') as folder:
        path = Path(folder) / 'client.json'; path.write_text(json.dumps(config)); path.chmod(0o600)
        process = subprocess.Popen([str(binary), 'run', '-config', str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   env=dict(os.environ, GOMAXPROCS='1', GOMEMLIMIT='64MiB'))
        try:
            for _ in range(100):
                if process.poll() is not None: raise RuntimeError('Client Xray exited')
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=0.1): break
                except OSError: time.sleep(0.1)
            else: raise RuntimeError('SOCKS startup timeout')
            yield port
        finally:
            process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill(); process.wait()


def https(port, host='api.ipify.org', path='/', limit=4096):
    raw = probe.socks_connect(port, host, 443)
    with ssl.create_default_context().wrap_socket(raw, server_hostname=host) as stream:
        stream.sendall(f'GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n'.encode())
        response = http.client.HTTPResponse(stream); response.begin()
        if response.status != 200: raise OSError('Unexpected HTTPS response')
        return response.read(limit)


def dns_udp(port):
    with socket.create_connection(('127.0.0.1', port), timeout=10) as control:
        control.sendall(b'\x05\x01\x00'); assert probe.receive(control, 2) == b'\x05\x00'
        control.sendall(b'\x05\x03\x00\x01'+bytes(6))
        reply=probe.receive(control,4); assert reply[:2]==b'\x05\x00' and reply[3]==1
        host=socket.inet_ntoa(probe.receive(control,4)); relay_port=struct.unpack('!H',probe.receive(control,2))[0]
        query=os.urandom(2)+b'\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x07example\x03com\x00\x00\x01\x00\x01'
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as udp:
            udp.settimeout(8)
            # Public UDP DNS may drop a datagram; retry without hiding a persistent failure.
            for attempt in range(3):
                udp.sendto(b'\x00\x00\x00\x01'+socket.inet_aton('1.1.1.1')+struct.pack('!H',53)+query,(host,relay_port))
                try:
                    response,_=udp.recvfrom(4096)
                    break
                except socket.timeout:
                    if attempt == 2: raise
            assert response[3]==1 and response[10:12]==query[:2] and response[12]&128


def exit_address(port):
    for host in ('api.ipify.org', 'checkip.amazonaws.com'):
        try:
            value=https(port,host).decode().strip()
            ipaddress.IPv4Address(value)
            return value
        except (OSError,ValueError,http.client.HTTPException):
            continue
    raise RuntimeError('Both independent HTTPS address checks failed')


def awg(args, reference):
    native=(args.profiles/'client-via-entry.conf').read_text()
    endpoint=next(l.split('=',1)[1].strip() for l in native.splitlines() if l.startswith('Endpoint'))
    host,port=endpoint.split(':'); assert host==args.entry
    address=next(l.split('=',1)[1].strip() for l in native.splitlines() if l.startswith('Address'))
    ns='kit-client'; veth='kt-host'; peer='kt-peer'; interface='kt-awg'
    nsdir=Path('/etc/netns')/ns
    if nsdir.exists(): raise ValueError('Old lab namespace exists')
    previous=run('sysctl','-n','net.ipv4.ip_forward'); process=None
    try:
        run('ip','netns','add',ns)
        nsdir.mkdir(parents=True);(nsdir/'resolv.conf').write_text('nameserver 1.1.1.1\n')
        run('ip','link','add',veth,'type','veth','peer','name',peer)
        run('ip','link','set',peer,'netns',ns)
        run('ip','address','add','172.30.0.1/30','dev',veth);run('ip','link','set',veth,'up')
        prefix=['ip','netns','exec',ns]
        run(*prefix,'ip','link','set','lo','up')
        run(*prefix,'ip','address','add','172.30.0.2/30','dev',peer);run(*prefix,'ip','link','set',peer,'up')
        run(*prefix,'ip','route','add',host+'/32','via','172.30.0.1')
        run('sysctl','-w','net.ipv4.ip_forward=1')
        run('nft','-f','-',data=f'table ip kit_client_lab {{\n chain nat {{\n type nat hook postrouting priority srcnat;\n ip saddr 172.30.0.0/30 ip daddr {host} udp dport {port} masquerade\n }}\n}}\n')
        process=subprocess.Popen(prefix+[str(args.bin/'amneziawg-go'),'-f',interface],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                                 env=dict(os.environ,GOMAXPROCS='1',GOMEMLIMIT='64MiB'))
        for _ in range(100):
            if subprocess.run(prefix+[str(args.bin/'awg'),'show',interface,'public-key'],capture_output=True).returncode==0:break
            time.sleep(0.1)
        raw='\n'.join(l for l in native.splitlines() if not l.startswith(('Address =','DNS =','MTU =')))
        run(*prefix,str(args.bin/'awg'),'setconf',interface,'/dev/stdin',data=raw+'\n')
        run(*prefix,'ip','address','add',address,'dev',interface)
        run(*prefix,'ip','link','set',interface,'mtu','1280','up')
        run(*prefix,'ip','route','add','default','dev',interface)
        code="import urllib.request;print(urllib.request.build_opener(urllib.request.ProxyHandler({})).open('https://api.ipify.org',timeout=25).read().decode())"
        value=run(*prefix,'python3','-c',code)
        assert value==reference,'Unexpected AWG exit IPv4'
        route=run(*prefix,'ip','route','get','1.1.1.1');assert interface in route
        # A specific direct route models the client's IP exclusion, without touching the VM's default route.
        run(*prefix,'ip','route','add','77.88.55.88/32','via','172.30.0.1','dev',peer)
        assert peer in run(*prefix,'ip','route','get','77.88.55.88')
        load="import urllib.request,json,time;t=time.monotonic();r=urllib.request.urlopen('http://203.0.113.99:19090/',timeout=25);n=len(r.read(8388609));assert n==8388608;print(json.dumps({'bytes':n,'seconds':time.monotonic()-t}))"
        result={'internet_exit_matches':True,'client_dns_through_tunnel':True,'direct_route_selected':True}
        if not args.quick:result['encrypted_load']=json.loads(run(*prefix,'python3','-c',load))
        return result
    finally:
        if process:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait()
        subprocess.run(['ip','netns','delete',ns],capture_output=True)
        subprocess.run(['ip','link','delete',veth],capture_output=True)
        subprocess.run(['nft','delete','table','ip','kit_client_lab'],capture_output=True)
        run('sysctl','-w','net.ipv4.ip_forward='+previous)
        if nsdir.exists():(nsdir/'resolv.conf').unlink();nsdir.rmdir()


def reality(args, reference):
    config=json.loads((args.profiles/'xray-client-via-entry.json').read_text())
    outbound=config['outbounds'][0]; endpoint=outbound['settings']['vnext'][0]
    assert endpoint['address']==args.entry
    with proxy(args.bin/'xray',config) as port:
        assert exit_address(port)==reference,'Unexpected REALITY exit IPv4'
        assert https(port,'example.com',limit=256),'Dual-stack destination failed'
        dns_udp(port)
        result={'internet_exit_matches':True,'dual_stack_https_over_ipv4':True,'udp_dns_over_tcp':True}
        blocked=False
        try:
            with probe.socks_connect(port,'localhost',22) as stream:
                stream.settimeout(3);blocked=not stream.recv(64)
        except OSError:blocked=True
        assert blocked,'Private SSH destination was exposed'
        result['private_destination_blocked']=True
        if not args.quick:
            with probe.socks_connect(port,'203.0.113.99',19090) as stream:
                started=time.monotonic()
                stream.sendall(b'GET / HTTP/1.1\r\nHost: benchmark.invalid\r\nConnection: close\r\n\r\n')
                response=http.client.HTTPResponse(stream);response.begin();body=response.read(8388609)
                assert response.status==200 and len(body)==8388608
                result['encrypted_load']={'bytes':len(body),'seconds':round(time.monotonic()-started,3)}
    if not args.quick:
        for field in ('id','shortId'):
            wrong=copy.deepcopy(config)
            if field=='id':wrong['outbounds'][0]['settings']['vnext'][0]['users'][0]['id']='00000000-0000-4000-8000-000000000001'
            else:wrong['outbounds'][0]['streamSettings']['realitySettings']['shortId']='ffffffffffffffff'
            rejected=False
            with proxy(args.bin/'xray',wrong) as port:
                try:https(port)
                except (OSError,http.client.HTTPException):rejected=True
            assert rejected,'Invalid client was accepted'
            result['invalid_'+field+'_rejected']=True
        context=ssl.create_default_context();context.set_alpn_protocols(['h2'])
        name=outbound['streamSettings']['realitySettings']['serverName']
        with socket.create_connection((args.entry,endpoint['port']),timeout=15) as raw:
            with context.wrap_socket(raw,server_hostname=name) as stream:
                assert stream.selected_alpn_protocol()=='h2';result['ordinary_tls_valid_target_certificate']=True
        with proxy(args.bin/'xray',config) as port:assert exit_address(port)==reference
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-test',action='store_true',required=True)
    parser.add_argument('--protocol',choices=('awg','reality','both'),required=True)
    parser.add_argument('--entry',required=True)
    parser.add_argument('--profiles',type=Path,required=True)
    parser.add_argument('--bin',type=Path,required=True)
    parser.add_argument('--reference-file',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--quick',action='store_true')
    args=parser.parse_args();address=ipaddress.IPv4Address(args.entry)
    if os.geteuid()!=0 or not any(address in ipaddress.IPv4Network(n) for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')):
        raise ValueError('Root in a private disposable VM required')
    reference=args.reference_file.read_text().strip();ipaddress.IPv4Address(reference)
    report={'protocol':args.protocol,'client_cpus':os.cpu_count(),'client_mem_kib':int(Path('/proc/meminfo').read_text().splitlines()[0].split()[1])}
    if args.protocol=='both':
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(awg,args,reference);second=pool.submit(reality,args,reference)
            report['awg'],report['reality']=first.result(),second.result()
        report['concurrent_protocol_checks']=True
    elif args.protocol=='awg':report['awg']=awg(args,reference)
    else:report['reality']=reality(args,reference)
    args.report.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


if __name__=='__main__':main()
