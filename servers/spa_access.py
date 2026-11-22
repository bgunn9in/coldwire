#!/usr/bin/env python3
"""Generate Coldwire SPA keys and firewall rules, or send a test request."""

import argparse
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import struct
import time


FRAME = struct.Struct('!4s8sQ16s4s32s')
SIZE = FRAME.size + 32
ZERO = bytes(32)
ZERO_ADDRESS = bytes(4)
DISCOVER, CHALLENGE, AUTHORIZE, GRANTED = b'CWQ1', b'CWC1', b'CWA1', b'CWO1'


def key_bytes(value):
    if not re.fullmatch(r'[0-9a-fA-F]{64}', value):
        raise ValueError('SPA keys must be 32 bytes in hexadecimal')
    return bytes.fromhex(value)


def key_id(key):
    return hashlib.sha256(key).digest()[:8]


def packet(kind, key, stamp, nonce, address=ZERO_ADDRESS, cookie=ZERO):
    body = FRAME.pack(kind, key_id(key), stamp, nonce, address, cookie)
    return body + hmac.digest(key, body, 'sha256')


def verify(data, keys):
    if len(data) != SIZE:
        return None
    fields = FRAME.unpack(data[:-32])
    key = keys.get(fields[1])
    if key is None or not hmac.compare_digest(hmac.digest(key, data[:-32], 'sha256'), data[-32:]):
        return None
    return key, fields


def request(host, port, key):
    keys = {key_id(key): key}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.settimeout(2)
        client.connect((str(ipaddress.IPv4Address(host)), port))
        nonce = secrets.token_bytes(16)
        client.send(packet(DISCOVER, key, int(time.time()), nonce))
        challenge = verify(client.recv(SIZE + 1), keys)
        if challenge is None or challenge[1][0] != CHALLENGE or challenge[1][3] != nonce:
            raise ValueError('Invalid SPA address challenge')
        _, _, stamp, _, address, cookie = challenge[1]
        client.send(packet(AUTHORIZE, key, stamp, nonce, address, cookie))
        if not hmac.compare_digest(client.recv(SIZE + 1), packet(GRANTED, key, stamp, nonce, address, cookie)):
            raise ValueError('Invalid SPA confirmation')


def firewall(role, iface, ssh_port, awg_port, peer, spa_port, retain_ssh=False):
    if not re.fullmatch(r'[a-zA-Z0-9_.-]{1,15}', iface):
        raise ValueError('Invalid WAN interface')
    peer = str(ipaddress.IPv4Address(peer))
    ssh = f'{{ 22, {ssh_port} }}' if retain_ssh and ssh_port != 22 else str(ssh_port)
    awg_entry = f'''  meta nfproto ipv4 udp dport {spa_port} limit rate 100/second burst 50 packets counter accept
  meta nfproto ipv4 udp dport {spa_port} counter drop'''
    awg_exit = f'''  ip saddr {peer} udp dport {awg_port} counter accept
  udp dport {awg_port} counter drop'''
    forward = f''' set spa_clients {{ type ipv4_addr; flags timeout; size 4096; }}
 chain relay {{
  type filter hook forward priority -5; policy accept;
  iifname "{iface}" ip daddr {peer} udp dport {awg_port} ct direction original ip saddr != @spa_clients counter drop
  iifname "{iface}" oifname "{iface}" meta nfproto ipv6 ct state new counter drop
 }}''' if role == 'entry' else f''' chain published {{
  type filter hook forward priority -5; policy accept;
  iifname != "{iface}" return
  ct direction reply return
  ct status dnat ip saddr {peer} meta l4proto udp ct original proto-dst {awg_port} accept
  counter drop
 }}'''
    return f'''table inet coldwire_access {{
{forward}
 chain wan {{
  type filter hook input priority -5; policy accept;
  iifname != "{iface}" return
  meta nfproto ipv4 udp sport 67 udp dport 68 accept
  ip6 saddr fe80::/10 udp sport 547 udp dport 546 accept
  ct state invalid drop
{awg_entry if role == 'entry' else awg_exit}
  meta nfproto ipv6 meta l4proto {{ tcp, udp }} ct state new counter drop
  ct state established,related accept
  meta nfproto ipv4 tcp dport {ssh} accept
  icmp type {{ destination-unreachable, time-exceeded, parameter-problem, echo-request }} accept
  icmpv6 type {{ destination-unreachable, packet-too-big, time-exceeded, parameter-problem }} accept
  ip6 hoplimit 255 icmpv6 type {{ nd-router-advert, nd-neighbor-solicit, nd-neighbor-advert }} accept
  counter drop
 }}
}}
'''


def port(value):
    parsed = int(value)
    if not 1 <= parsed <= 65535:
        raise argparse.ArgumentTypeError('Expected a port in 1–65535')
    return parsed


def generate(server_file, device_file):
    device = secrets.token_hex(32)
    config = json.dumps({'cookie_key': secrets.token_hex(32), 'devices': [device]})
    created = []
    try:
        for path, contents in ((server_file, config), (device_file, device)):
            with path.open('x', encoding='utf-8') as stream:
                created.append(path)
                stream.write(contents + '\n')
    except OSError:
        for path in created:
            path.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    keys = commands.add_parser('keys')
    keys.add_argument('server_key_file', type=Path)
    keys.add_argument('device_key_file', type=Path)
    render = commands.add_parser('firewall')
    render.add_argument('role', choices=('entry', 'exit'))
    render.add_argument('interface')
    render.add_argument('peer', type=ipaddress.IPv4Address)
    render.add_argument('--ssh-port', type=port, default=22222)
    render.add_argument('--awg-port', type=port, default=32497)
    render.add_argument('--spa-port', type=port, default=62201)
    render.add_argument('--retain-ssh', action='store_true')
    client = commands.add_parser('request')
    client.add_argument('address', type=ipaddress.IPv4Address)
    client.add_argument('key_file', type=Path)
    client.add_argument('--port', type=port, default=62201)
    args = parser.parse_args()
    try:
        if args.command == 'keys':
            os.umask(0o077)
            generate(args.server_key_file, args.device_key_file)
        elif args.command == 'firewall':
            if args.spa_port == args.awg_port:
                raise ValueError('The AWG and SPA UDP ports must differ')
            print(firewall(args.role, args.interface, args.ssh_port, args.awg_port, args.peer, args.spa_port, args.retain_ssh), end='')
        else:
            request(args.address, args.port, key_bytes(args.key_file.read_text().strip()))
    except (OSError, ValueError) as error:
        parser.exit(1, f'SPA: {error}\n')


if __name__ == '__main__':
    main()
