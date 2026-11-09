#!/usr/bin/env python3
"""Privileged LAB test: private-address Debian/Ubuntu VM only; creates a second peer."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
STATE = Path('/etc/awg-relay-kit-exit')
BIN = Path('/usr/local/libexec/awg-relay-kit')
SERVICE = 'awg-relay-kit-exit.service'


def run(*args, data=None):
    p = subprocess.run(args, input=data, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f'Lab command {args[0]} failed (exit {p.returncode}); private output suppressed')
    return p.stdout.strip()


def rss(pid):
    return int(next(l.split()[1] for l in Path(f'/proc/{pid}/status').read_text().splitlines() if l.startswith('VmRSS:')))


def cpu_ticks(pid):
    fields = Path(f'/proc/{pid}/stat').read_text().split()
    return int(fields[13]) + int(fields[14])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-test', action='store_true', required=True)
    parser.add_argument('--client', default='vm1')
    parser.add_argument('--second-client', default='vm2')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise ValueError('Root required in the disposable lab VM')
    state = json.loads((STATE / 'server.json').read_text())
    if state.get('installer') != 'awg-relay-kit-native-v1' or not any(ipaddress.IPv4Address(state['endpoint']) in ipaddress.IPv4Network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')):
        raise ValueError('This test refuses a public-address or non-native installation')
    resources = {'cpus': os.cpu_count(), 'mem_total_kib': int(Path('/proc/meminfo').read_text().splitlines()[0].split()[1])}
    echo = socket.socket()
    echo.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    echo.bind(('10.8.1.1', 19091))
    echo.listen(5)
    def echo_server():
        try:
            while True:
                connection, _ = echo.accept()
                with connection:
                    connection.sendall(b'awg-native-ok')
        except OSError:
            pass
    threading.Thread(target=echo_server, daemon=True).start()
    pid = int(run('systemctl', 'show', SERVICE, '--property=MainPID', '--value'))
    report = dict(resources, server_idle_rss_kib=rss(pid), docker_installed=bool(shutil.which('docker')), go_compiler_installed=bool(shutil.which('go')))
    namespaces, processes, logs = [], [], []
    def create_client(name, index):
        ns, iface, host, peer = f'awg-lab-{index}', f'awglab{index}', f'awgh{index}', f'awgp{index}'
        nsdir = Path('/etc/netns') / ns
        if nsdir.exists():
            raise ValueError('Old lab namespace configuration exists')
        run('ip', 'netns', 'add', ns)
        namespaces.append((ns, nsdir))
        nsdir.mkdir(parents=True, mode=0o700)
        (nsdir / 'resolv.conf').write_text('nameserver 1.1.1.1\nnameserver 1.0.0.1\n')
        run('ip', 'link', 'add', host, 'type', 'veth', 'peer', 'name', peer)
        run('ip', 'link', 'set', peer, 'netns', ns)
        run('ip', 'address', 'add', f'172.31.{250 + index}.1/30', 'dev', host)
        run('ip', 'link', 'set', host, 'up')
        run('ip', 'netns', 'exec', ns, 'ip', 'link', 'set', 'lo', 'up')
        run('ip', 'netns', 'exec', ns, 'ip', 'address', 'add', f'172.31.{250 + index}.2/30', 'dev', peer)
        run('ip', 'netns', 'exec', ns, 'ip', 'link', 'set', peer, 'up')
        run('ip', 'netns', 'exec', ns, 'ip', 'route', 'add', state['endpoint'] + '/32', 'via', f'172.31.{250 + index}.1', 'dev', peer)
        log = (Path('/root') / f'{ns}.log').open('w')
        logs.append(log)
        process = subprocess.Popen(['ip', 'netns', 'exec', ns, 'env', 'GOMAXPROCS=1', 'GOMEMLIMIT=64MiB', str(BIN / 'amneziawg-go'), '-f', iface], stdout=log, stderr=log)
        processes.append(process)
        for _ in range(100):
            if (Path('/run/amneziawg') / f'{iface}.sock').exists():
                break
            time.sleep(0.1)
        native = (Path('/root/awg-relay-kit-clients') / name / 'client.conf').read_text()
        address = next(l.split('=', 1)[1].strip() for l in native.splitlines() if l.startswith('Address ='))
        raw = '\n'.join(l for l in native.splitlines() if not l.startswith(('Address =', 'DNS =', 'MTU =')))
        run('ip', 'netns', 'exec', ns, str(BIN / 'awg'), 'setconf', iface, '/dev/stdin', data=raw + '\n')
        run('ip', 'netns', 'exec', ns, 'ip', 'address', 'add', address, 'dev', iface)
        run('ip', 'netns', 'exec', ns, 'ip', 'link', 'set', iface, 'mtu', '1280', 'up')
        run('ip', 'netns', 'exec', ns, 'ip', 'route', 'add', 'default', 'dev', iface)
        return ns
    try:
        first = create_client(args.client, 1)
        probe = "import socket;s=socket.create_connection(('10.8.1.1',19091),timeout=25);r=s.recv(100);assert r==b'awg-native-ok';print('TCP echo passed')"
        report['tunnel_probe'] = run('ip', 'netns', 'exec', first, 'python3', '-c', probe)
        request = "import urllib.request;print(urllib.request.build_opener(urllib.request.ProxyHandler({})).open('https://api.ipify.org',timeout=25).read().decode())"
        report['internet_ipv4'] = run('ip', 'netns', 'exec', first, 'python3', '-c', request)
        if args.second_client not in state['clients']:
            run('python3', str(ROOT / 'install_exit.py'), 'add-client', '--name', args.second_client)
        if int(run('systemctl', 'show', SERVICE, '--property=MainPID', '--value')) != pid:
            raise RuntimeError('Adding the peer restarted the server')
        report['first_after_add'] = run('ip', 'netns', 'exec', first, 'python3', '-c', probe)
        second = create_client(args.second_client, 2)
        report['second_internet_ipv4'] = run('ip', 'netns', 'exec', second, 'python3', '-c', request)
        listener = socket.socket()
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('10.8.1.1', 19090))
        listener.listen(1)
        def send_load():
            try:
                connection, _ = listener.accept()
                with connection:
                    connection.settimeout(3)
                    payload = bytes(65536)
                    while True:
                        connection.sendall(payload)
            except OSError:
                pass
            finally:
                listener.close()
        thread = threading.Thread(target=send_load, daemon=True)
        thread.start()
        load_code = "import socket,time,json;s=socket.create_connection(('10.8.1.1',19090));s.settimeout(5);t=time.monotonic();n=0\nwhile time.monotonic()-t<10:n+=len(s.recv(65536))\nprint(json.dumps({'bytes':n,'seconds':time.monotonic()-t}))"
        before_cpu, start = cpu_ticks(pid), time.monotonic()
        load = subprocess.Popen(['ip', 'netns', 'exec', first, 'python3', '-c', load_code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        peak = rss(pid)
        while load.poll() is None:
            peak = max(peak, rss(pid))
            time.sleep(0.1)
        output, _ = load.communicate()
        if load.returncode:
            raise RuntimeError('Traffic load failed')
        sample = json.loads(output)
        report['tcp_mbps_shared_single_vcpu'] = round(8 * sample['bytes'] / sample['seconds'] / 1_000_000, 2)
        report['server_cpu_percent_during_load'] = round(100 * (cpu_ticks(pid) - before_cpu) / os.sysconf('SC_CLK_TCK') / (time.monotonic() - start), 2)
        report['server_sampled_peak_rss_kib'] = peak
        report['server_after_load_rss_kib'] = rss(pid)
        report['runtime_peers'] = len(run(str(BIN / 'awg'), 'show', 'awg0', 'peers').split())
        report['fresh_handshakes'] = sum(int(l.split()[1]) > 0 for l in run(str(BIN / 'awg'), 'show', 'awg0', 'latest-handshakes').splitlines())
        report['nft_counter_output'] = run('nft', 'list', 'table', 'ip', 'awg_exit')
        args.report.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({k: v for k, v in report.items() if not isinstance(v, str)}, indent=2))
        print('PASS: native client Internet/NAT, second peer without restart and encrypted TCP load')
    finally:
        echo.close()
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for ns, nsdir in namespaces:
            subprocess.run(['ip', 'netns', 'delete', ns], capture_output=True)
            if nsdir.exists():
                for path in nsdir.iterdir():
                    path.unlink()
                nsdir.rmdir()
        for log in logs:
            log.close()


if __name__ == '__main__':
    main()
