#!/usr/bin/env python3
"""LAB ONLY: sample server resources and serve a bounded, local benchmark body."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import threading
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-test',action='store_true',required=True)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    if os.geteuid()!=0:raise ValueError('Root in disposable VM required')
    states=[p for p in (Path('/etc/awg-relay-kit-exit/server.json'),Path('/etc/awg-relay-kit-xray/server.json')) if p.exists()]
    if not states:raise ValueError('No test installation')
    for p in states:
        address=ipaddress.IPv4Address(json.loads(p.read_text())['endpoint'])
        if not any(address in ipaddress.IPv4Network(n) for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')):
            raise ValueError('Public endpoints are refused')
    xray_path=Path('/etc/awg-relay-kit-xray/config.json')
    original_xray=None
    if xray_path.exists():
        original_xray=xray_path.read_bytes();config=json.loads(original_xray)
        # Xray 26 blocks documentation networks by default. Permit ONLY this VM fixture and port.
        config['outbounds'][0]['settings']={'finalRules':[{'action':'allow','network':'tcp','ip':['203.0.113.99/32'],'port':'19090'}]}
        xray_path.write_text(json.dumps(config));xray_path.chmod(0o600)
        subprocess.run(['systemctl','restart','awg-relay-kit-xray.service'],check=True)
        endpoint=config['inbounds'][0]
        for _ in range(100):
            try:
                with socket.create_connection((endpoint['listen'],endpoint['port']),timeout=.1):break
            except OSError:time.sleep(.1)
        else:raise RuntimeError('Lab Xray did not become ready')
    bench='203.0.113.99'
    assigned=json.loads(subprocess.check_output(['ip','-j','address','show','dev','lo']))
    if any(a.get('local')==bench for d in assigned for a in d['addr_info']):raise ValueError('Old benchmark address exists')
    subprocess.run(['ip','address','add',bench+'/32','dev','lo'],check=True)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*unused):pass
        def do_GET(self):
            self.send_response(200);self.send_header('Content-Length',str(8*1024*1024));self.end_headers()
            try:
                for _ in range(512):self.wfile.write(bytes(16384));time.sleep(.004)
            except OSError:pass
    server=ThreadingHTTPServer((bench,19090),Handler);server.daemon_threads=True
    threading.Thread(target=server.serve_forever,daemon=True).start()
    stop=False
    def halt(*unused):
        nonlocal stop
        stop=True
    signal.signal(signal.SIGTERM,halt)
    def ticks(pid):
        f=Path(f'/proc/{pid}/stat').read_text().split();return int(f[13])+int(f[14])
    samples={};start=time.monotonic()
    ready=Path('/root/kit-observer.ready');ready.write_text('ready\n')
    try:
        for service in ('awg-relay-kit-exit.service','awg-relay-kit-xray.service'):
            value=subprocess.check_output(['systemctl','show',service,'-p','MainPID','--value']).strip()
            pid=int(value or b'0')
            if pid:samples[service]={'pid':pid,'start_ticks':ticks(pid),'peak_rss_kib':0,'idle_rss_kib':0}
        while not stop and time.monotonic()-start<160:
            for data in samples.values():
                rss=int(next(l.split()[1] for l in Path(f'/proc/{data["pid"]}/status').read_text().splitlines() if l.startswith('VmRSS:')))
                if not data['idle_rss_kib']:data['idle_rss_kib']=rss
                data['peak_rss_kib']=max(data['peak_rss_kib'],rss);data['ticks']=ticks(data['pid'])
            time.sleep(.1)
    finally:
        server.shutdown();server.server_close()
        subprocess.run(['ip','address','delete',bench+'/32','dev','lo'],check=True)
        ready.unlink(missing_ok=True)
        if original_xray is not None:
            xray_path.write_bytes(original_xray);xray_path.chmod(0o600)
            subprocess.run(['systemctl','restart','awg-relay-kit-xray.service'],check=True)
        for data in samples.values():
            data['cpu_percent']=round(100*(data.pop('ticks',data['start_ticks'])-data.pop('start_ticks'))/os.sysconf('SC_CLK_TCK')/(time.monotonic()-start),2)
        report={'server_cpus':os.cpu_count(),'server_mem_kib':int(Path('/proc/meminfo').read_text().splitlines()[0].split()[1]),
                'seconds':round(time.monotonic()-start,2),'services':samples}
        args.report.write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
