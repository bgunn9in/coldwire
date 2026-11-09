#!/usr/bin/env python3
"""Temporary AWG handshake from B through A; no client/default route is changed."""
import argparse
import fcntl
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from exit_config import client_profile

STATE = Path('/etc/awg-relay-kit-exit')
BIN = Path('/usr/local/libexec/awg-relay-kit')
IFACE = 'awgrprobe'


def run(*args, data=None):
    p = subprocess.run(args, input=data, text=True, capture_output=True)
    if p.returncode:
        raise RuntimeError(args[0] + ' failed; private command input/output suppressed')
    return p.stdout.strip()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--entry', required=True)
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--timeout', type=int, default=45)
    args = p.parse_args()
    ipaddress.IPv4Address(args.entry)
    if not 1 <= args.port <= 65535 or not 1 <= args.timeout <= 120:
        raise ValueError('Invalid port or timeout')
    if os.geteuid() != 0:
        raise ValueError('Root required on the new native exit')
    with (STATE / 'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = json.loads((STATE / 'server.json').read_text())
        if state.get('installer') != 'awg-relay-kit-native-v1':
            raise ValueError('Not a native kit-managed exit')
        if subprocess.run(['ip', 'link', 'show', IFACE], capture_output=True).returncode == 0:
            raise ValueError('Probe interface already exists')
        used = {v['address'] for v in state['clients'].values()}
        address = next((f'10.8.1.{n}' for n in range(254, 1, -1) if f'10.8.1.{n}' not in used), None)
        if not address:
            raise ValueError('No free address for a temporary probe')
        private = run(str(BIN / 'awg'), 'genkey')
        public = run(str(BIN / 'awg'), 'pubkey', data=private + '\n')
        profile_state = dict(state, endpoint=args.entry, port=args.port)
        exported = client_profile(profile_state, 'relay-probe', private, public, address)
        client = json.loads(exported['containers'][0]['awg']['last_config'])
        raw = '\n'.join(l for l in client['config'].splitlines() if not l.startswith(('Address =', 'DNS =', 'MTU =')))
        raw = raw.replace('PersistentKeepalive = 25-35', 'PersistentKeepalive = 1')
        process = None
        registered = False
        try:
            run(str(BIN / 'awg'), 'set', 'awg0', 'peer', public, 'preshared-key', '/dev/stdin', 'allowed-ips', address + '/32', data=state['psk'] + '\n')
            registered = True
            process = subprocess.Popen([str(BIN / 'amneziawg-go'), '-f', IFACE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       env=dict(os.environ, GOMAXPROCS='1', GOMEMLIMIT='32MiB'))
            deadline = time.monotonic() + args.timeout
            while time.monotonic() < deadline:
                check = subprocess.run([str(BIN / 'awg'), 'show', IFACE, 'public-key'], capture_output=True)
                if check.returncode == 0:
                    break
                if process.poll() is not None:
                    raise RuntimeError('Probe process exited')
                time.sleep(0.1)
            run(str(BIN / 'awg'), 'setconf', IFACE, '/dev/stdin', data=raw + '\n')
            # No IP address and no route are added: PersistentKeepalive initiates an authenticated exchange.
            run('ip', 'link', 'set', IFACE, 'mtu', '1280', 'up')
            success = False
            while time.monotonic() < deadline:
                latest = run(str(BIN / 'awg'), 'show', IFACE, 'latest-handshakes').split()
                endpoints = dict(l.split() for l in run(str(BIN / 'awg'), 'show', 'awg0', 'endpoints').splitlines())
                server_latest = dict(l.split() for l in run(str(BIN / 'awg'), 'show', 'awg0', 'latest-handshakes').splitlines())
                if latest and int(latest[-1]) > 0 and int(server_latest.get(public, '0')) > 0 and endpoints.get(public, '').rsplit(':', 1)[0] == args.entry:
                    success = True
                    break
                time.sleep(0.25)
            if not success:
                raise RuntimeError('No verified handshake through entry before timeout')
        finally:
            if process:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            if registered:
                run(str(BIN / 'awg'), 'set', 'awg0', 'peer', public, 'remove')
        print(json.dumps({'handshake': True, 'server_sees_entry': True, 'entry': args.entry, 'port': args.port, 'temporary_peer_removed': True}))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError):
        print('Relay probe failed; keys and private output suppressed.', file=sys.stderr)
        sys.exit(1)
