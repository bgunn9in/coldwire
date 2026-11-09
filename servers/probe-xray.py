#!/usr/bin/env python3
"""Authenticated REALITY application probe through A, without changing routes."""
import argparse
import http.client
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from xray_config import client_config
from install_xray import load_owned, BIN


def receive(stream, length):
    result = b''
    while len(result) < length:
        part = stream.recv(length - len(result))
        if not part:
            raise OSError('SOCKS stream closed')
        result += part
    return result


def socks_connect(port, host, target_port):
    stream = socket.create_connection(('127.0.0.1', port), timeout=10)
    try:
        stream.sendall(b'\x05\x01\x00')
        if receive(stream, 2) != b'\x05\x00':
            raise OSError('SOCKS authentication failed')
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            name = host.encode('idna')
            destination = b'\x03' + bytes([len(name)]) + name
        else:
            destination = (b'\x01' if address.version == 4 else b'\x04') + address.packed
        stream.sendall(b'\x05\x01\x00' + destination + struct.pack('!H', target_port))
        header = receive(stream, 4)
        if header[:2] != b'\x05\x00':
            raise OSError('SOCKS connect failed')
        length = {1: 4, 4: 16}.get(header[3])
        if header[3] == 3:
            length = receive(stream, 1)[0]
        if length is None:
            raise OSError('SOCKS address type')
        receive(stream, length + 2)
        return stream
    except BaseException:
        stream.close()
        raise


def check(config, server_port, expected_entry, timeout=45):
    with socket.socket() as reservation:
        reservation.bind(('127.0.0.1', 0))
        port = reservation.getsockname()[1]
    config['inbounds'][0]['port'] = port
    with tempfile.TemporaryDirectory(prefix='reality-probe-', dir='/run') as directory:
        path = Path(directory) / 'client.json'
        path.write_text(json.dumps(config))
        path.chmod(0o600)
        process = subprocess.Popen([str(BIN / 'xray'), 'run', '-config', str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   env=dict(os.environ, GOMAXPROCS='1', GOMEMLIMIT='48MiB'))
        try:
            deadline = time.monotonic() + timeout
            while True:
                if process.poll() is not None:
                    raise RuntimeError('Probe process exited')
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=0.2):
                        break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError('Probe SOCKS timeout')
                    time.sleep(0.1)
            for host in ('api.ipify.org', 'checkip.amazonaws.com'):
                try:
                    raw = socks_connect(port, host, 443)
                    with ssl.create_default_context().wrap_socket(raw, server_hostname=host) as stream:
                        connections = subprocess.check_output(['ss', '-H', '-nt', 'state', 'established', f'( sport = :{server_port} )']).decode()
                        peer_seen = any(line.split()[-1].rsplit(':', 1)[0].strip('[]').removeprefix('::ffff:') == expected_entry
                                        for line in connections.splitlines() if line.split())
                        if not peer_seen:
                            raise RuntimeError('Exit did not see entry TCP endpoint')
                        stream.sendall(f'GET / HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n'.encode())
                        response = http.client.HTTPResponse(stream)
                        response.begin()
                        body = response.read(4096).decode().strip()
                        if response.status != 200:
                            raise OSError('IP check failed')
                        ipaddress.IPv4Address(body)
                        return body
                except (OSError, ValueError, http.client.HTTPException):
                    if time.monotonic() >= deadline:
                        break
            raise RuntimeError('No authenticated HTTPS response through REALITY')
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--entry', required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--client', required=True)
    args = parser.parse_args()
    ipaddress.IPv4Address(args.entry)
    if not 1 <= args.port <= 65535 or os.geteuid() != 0:
        raise ValueError('Valid TCP port and root required')
    state = load_owned()
    result = check(client_config(state, state['clients'][args.client], args.entry, args.port), state['port'], args.entry)
    endpoint = ipaddress.IPv4Address(state['endpoint'])
    if endpoint.is_global and str(endpoint) != result:
        raise RuntimeError('Unexpected Internet exit IPv4')
    print(json.dumps({'application_data': True, 'server_sees_entry': True, 'temporary_process_removed': True}))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, TypeError):
        print('REALITY probe failed; private configuration/output suppressed.', file=sys.stderr)
        sys.exit(1)
