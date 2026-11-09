#!/usr/bin/env python3
"""Short systemd start/stop helper; only amneziawg-go remains resident."""
import json
from pathlib import Path
import subprocess
import sys
import time

STATE = Path('/etc/awg-relay-kit-exit')
AWG = '/usr/local/libexec/awg-relay-kit/awg'


def command(*args, data=None, optional=False):
    result = subprocess.run(args, input=data, text=True, capture_output=True)
    if result.returncode and not optional:
        raise RuntimeError(args[0] + ' failed; private command input/error was not printed')
    return result


def down():
    command('/usr/sbin/nft', 'delete', 'table', 'ip', 'awg_exit', optional=True)
    Path('/proc/sys/net/ipv4/ip_forward').write_text('0\n')


def up():
    config = json.loads((STATE / 'server.json').read_text())
    for _ in range(300):
        if command(AWG, 'show', 'awg0', 'public-key', optional=True).returncode == 0:
            break
        time.sleep(0.1)
    else:
        raise RuntimeError('AWG userspace socket did not become ready')
    raw = '\n'.join(line for line in (STATE / 'awg0.conf').read_text().splitlines()
                    if not line.startswith(('Address =', 'MTU =')))
    command(AWG, 'setconf', 'awg0', '/dev/stdin', data=raw + '\n')
    command('/usr/sbin/ip', 'address', 'add', '10.8.1.1/24', 'dev', 'awg0')
    command('/usr/sbin/ip', 'link', 'set', 'dev', 'awg0', 'mtu', '1280', 'up')
    existing = command('/usr/sbin/nft', 'list', 'table', 'ip', 'awg_exit', optional=True).returncode == 0
    rules = ('delete table ip awg_exit\n' if existing else '') + (STATE / 'exit.nft').read_text()
    command('/usr/sbin/nft', '-f', '-', data=rules)
    Path('/proc/sys/net/ipv4/ip_forward').write_text('1\n')
    if command(AWG, 'show', 'awg0', 'public-key').stdout.strip() != config['public_key']:
        raise RuntimeError('Unexpected server public key')
    if command(AWG, 'show', 'awg0', 'listen-port').stdout.strip() != str(config['port']):
        raise RuntimeError('Unexpected UDP port')


try:
    {'up': up, 'down': down}[sys.argv[1]]()
except (OSError, ValueError, KeyError, RuntimeError) as error:
    print('AWG network setup failed: ' + str(error), file=sys.stderr)
    sys.exit(1)
