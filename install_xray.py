#!/usr/bin/env python3
"""Install native Xray/REALITY on clean Ubuntu 22.04/24.04/26.04 LTS or Debian 12/13 amd64."""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import time

import install_exit as awg
from exit_config import write_private, replace_private, public_binary_directory
from xray_config import target, new_client, server_config

ROOT = Path(__file__).resolve().parent
STATE = Path('/etc/awg-relay-kit-xray')
CLIENTS = Path('/root/awg-relay-kit-xray-clients')
BIN = Path('/usr/local/libexec/awg-relay-kit-xray')
SERVICE = 'awg-relay-kit-xray.service'
UNIT = Path('/etc/systemd/system') / SERVICE
BUNDLE = ROOT / 'dist/xray-native-linux-amd64.tar.gz'
VERSION = '26.10.21'
BUNDLE_SHA256 = '874e6b0a6e2283777083ec49ee98d0c13f39c7e7694e1ebd1fbc4e93ce61bba2'
UPSTREAM_SHA256 = '0eec3ed4163c273d8c8bf821f7d219e257921cf584aa3fb970715e458e631978'
MARKER = 'awg-relay-kit-xray-v1'
CANDIDATES = ('www.debian.org', 'www.wikipedia.org', 'www.kernel.org')
run = awg.run


def read_bundle(path):
    checksum = path.with_suffix('').with_suffix('.sha256').read_text().split()[0]
    if checksum != BUNDLE_SHA256 or hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
        raise ValueError('Xray bundle SHA256 mismatch')
    expected = {'xray', 'LICENSE', 'manifest.json'}
    with tarfile.open(path, 'r:gz') as archive:
        members = archive.getmembers()
        if len(members) != 3 or {m.name for m in members} != expected or any(not m.isfile() or m.size > 80_000_000 for m in members):
            raise ValueError('Unexpected Xray archive contents')
        files = {m.name: archive.extractfile(m).read() for m in members}
    manifest = json.loads(files['manifest.json'])
    if manifest.get('version') != VERSION or manifest.get('platform') != 'linux-amd64' or manifest.get('upstream_sha256') != UPSTREAM_SHA256:
        raise ValueError('Unexpected Xray provenance')
    if set(manifest['files']) != {'xray', 'LICENSE'} or any(hashlib.sha256(files[n]).hexdigest() != h for n, h in manifest['files'].items()):
        raise ValueError('Xray internal SHA256 mismatch')
    return files


def choose_target(requested=None):
    for value in (requested,) if requested else secrets.SystemRandom().sample(CANDIDATES, len(CANDIDATES)):
        host, port = target(value)
        try:
            # Python 3.10's EC_GROUP API rejects X25519; OpenSSL's groups API supports it.
            result = subprocess.run(['openssl', 's_client', '-4', '-connect', f'{host}:{port}',
                                     '-servername', host, '-tls1_3', '-groups', 'X25519', '-alpn', 'h2',
                                     '-verify_hostname', host, '-verify_return_error', '-no_ign_eof'],
                                    input='', text=True, capture_output=True, timeout=12)
            if result.returncode == 0 and 'ALPN protocol: h2' in result.stdout:
                return f'{host}:{port}', host
        except (OSError, subprocess.TimeoutExpired):
            continue
    raise ValueError('No suitable REALITY TLS1.3/h2/X25519 target; use --target HOST[:PORT]')


def preflight(args):
    awg.require_supported_host()
    address = ipaddress.IPv4Address(args.endpoint)
    private = args.allow_private_endpoint and any(address in ipaddress.IPv4Network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
    if (not address.is_global or address.is_multicast) and not private:
        raise ValueError('Use a public endpoint; local VM requires --allow-private-endpoint')
    if args.entry:
        entry = ipaddress.IPv4Address(args.entry)
        local = args.allow_private_endpoint and any(entry in ipaddress.IPv4Network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
        if (not entry.is_global or entry.is_multicast) and not local or entry == address:
            raise ValueError('Use a different valid entry IPv4')
    if not all(1 <= n <= 65535 for n in (args.port, args.entry_port)) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,47}', args.client):
        raise ValueError('Invalid port or client name')
    if any(p.exists() for p in (STATE, BIN, CLIENTS, UNIT, Path('/opt/amnezia'))):
        raise ValueError('Existing installation/output detected; never overwrite')
    if shutil.which('docker') or Path('/var/lib/docker').exists():
        raise ValueError('Use a clean VPS without Docker')
    assigned = {a['local'] for d in json.loads(run('ip', '-j', 'address')) for a in d['addr_info'] if a['family'] == 'inet'}
    if args.endpoint not in assigned or run('ss', '-H', '-ltn', f'sport = :{args.port}'):
        raise ValueError('Endpoint is not assigned or TCP port is occupied')
    managed = args.with_awg and awg.STATE.exists()
    if awg.STATE.exists() and not managed:
        raise ValueError('Existing AWG requires explicit --with-awg coordination')
    if managed:
        owned = awg.load_owned()
        if owned['endpoint'] != args.endpoint or run(str(awg.BIN / 'awg'), 'show', 'awg0', 'public-key') != owned['public_key']:
            raise ValueError('Existing AWG is not the expected healthy installation')
    if run('sysctl', '-n', 'net.ipv4.ip_forward') != ('1' if managed else '0'):
        raise ValueError('Unexpected forwarding state')
    tables = run('nft', 'list', 'tables') if shutil.which('nft') else ''
    if tables != ('table ip awg_exit' if managed else ''):
        raise ValueError('Foreign nftables tables detected')
    if shutil.which('ufw') and 'Status: active' in run('ufw', 'status'):
        raise ValueError('Active UFW detected')
    read_bundle(getattr(args, 'bundle', BUNDLE))


def prepare(bundle):
    files = read_bundle(bundle)
    if not shutil.which('openssl') or not Path('/etc/ssl/certs/ca-certificates.crt').exists():
        run('apt-get', 'update', '-o', 'Acquire::Retries=3', visible=True)
        run('apt-get', 'install', '-y', '--no-install-recommends', 'ca-certificates', 'openssl', visible=True)
    public_binary_directory(BIN)
    for name, content in files.items():
        write_private(BIN / name, content)
        (BIN / name).chmod(0o755 if name == 'xray' else 0o644)
    for source in (bundle, bundle.with_suffix('').with_suffix('.sha256')):
        shutil.copy2(source, BIN / source.name)


def service_text():
    return f'''[Unit]
Description=Native VLESS REALITY exit
Wants=network-online.target
After=network-online.target
[Service]
Type=simple
DynamicUser=yes
LoadCredential=config.json:{STATE}/config.json
ExecStart={BIN}/xray run -config ${{CREDENTIALS_DIRECTORY}}/config.json
Restart=on-failure
RestartSec=2
UMask=0077
Environment=GOMAXPROCS=1 GOMEMLIMIT=96MiB
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
AmbientCapabilities=CAP_NET_BIND_SERVICE
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
MemoryAccounting=yes
TasksMax=64
[Install]
WantedBy=multi-user.target
'''


def save(state):
    replace_private(STATE / 'config.json', json.dumps(server_config(state), indent=2) + '\n')
    replace_private(STATE / 'server.json', json.dumps(state, indent=2) + '\n')


def load_owned():
    state = json.loads((STATE / 'server.json').read_text())
    if state.get('installer') != MARKER or json.loads((STATE / 'config.json').read_text()) != server_config(state):
        raise ValueError('Not a consistent kit-managed Xray installation')
    return state


def wait_ready(port):
    for _ in range(100):
        if run('ss', '-H', '-ltn', f'sport = :{port}'):
            run('systemctl', 'is-active', '--quiet', SERVICE)
            return
        time.sleep(.1)
    raise RuntimeError('Xray TCP listener did not become ready')


def activate(state):
    STATE.mkdir(mode=0o700)
    save(state)
    run(str(BIN / 'xray'), 'run', '-test', '-config', str(STATE / 'config.json'))
    write_private(UNIT, service_text())
    run('systemctl', 'daemon-reload')
    try:
        run('systemctl', 'enable', '--now', SERVICE)
        wait_ready(state['port'])
    except BaseException:
        run('systemctl', 'disable', '--now', SERVICE)
        raise


def export(files, name):
    folder = CLIENTS / name
    folder.mkdir(mode=0o700)
    for filename, data in files.items():
        write_private(folder / filename, data)


def install(args):
    args.phase = 'PREFLIGHT'
    preflight(args)
    args.phase = 'TLS_TARGET'
    destination, name = choose_target(args.target)
    if args.check_only:
        print('Xray preflight passed; target:', destination)
        return
    args.phase = 'BINARY_INSTALL'
    prepare(BUNDLE)
    args.phase = 'KEY_GENERATION'
    output = run(str(BIN / 'xray'), 'x25519')
    values = dict(line.split(':', 1) for line in output.splitlines() if ':' in line)
    private = next((v.strip() for k, v in values.items() if k.strip().lower() == 'privatekey'), '')
    public = next((v.strip() for k, v in values.items() if 'publickey' in k.lower() or k.strip().lower() == 'password'), '')
    if not all(re.fullmatch(r'[A-Za-z0-9_-]{43}', v) for v in (private, public)):
        raise ValueError('Unexpected pinned Xray key generation format')
    state = {'installer': MARKER, 'endpoint': args.endpoint, 'entry': args.entry, 'port': args.port,
             'entry_port': args.entry_port, 'target': destination, 'server_name': name,
             'private_key': private, 'public_key': public, 'clients': {}}
    state, files = new_client(state, args.client)
    CLIENTS.mkdir(mode=0o700)
    export(files, args.client)
    args.phase = 'ACTIVATION'
    activate(state)
    print('Native Xray/REALITY ready; private client exports:', CLIENTS / args.client)


def add_client(args):
    import fcntl
    with (STATE / 'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = load_owned()
        changed, files = new_client(previous, args.name)
        export(files, args.name)
        try:
            save(changed)
            run(str(BIN / 'xray'), 'run', '-test', '-config', str(STATE / 'config.json'))
            run('systemctl', 'restart', SERVICE)
            wait_ready(changed['port'])
        except BaseException:
            save(previous)
            run('systemctl', 'restart', SERVICE)
            wait_ready(previous['port'])
            raise
    print('Xray client added; Xray restarted; AWG was not restarted. Private exports:', CLIENTS / args.name)


def backup(args):
    import fcntl
    with (STATE / 'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        load_owned()
        args.output.mkdir(mode=0o700)
        shutil.copytree(STATE, args.output / 'state')
        shutil.copytree(CLIENTS, args.output / 'clients')
        for filename in (BUNDLE.name, 'xray-native-linux-amd64.sha256'):
            shutil.copy2(BIN / filename, args.output / filename)
    print('Secret Xray backup:', args.output)


def restore(args):
    state = json.loads((args.backup / 'state/server.json').read_text())
    if state.get('installer') != MARKER or json.loads((args.backup / 'state/config.json').read_text()) != server_config(state):
        raise ValueError('Invalid Xray backup')
    args.port, args.entry, args.entry_port, args.client = state['port'], state.get('entry'), state['entry_port'], 'restored'
    args.bundle = args.backup / BUNDLE.name
    preflight(args)
    prepare(args.backup / BUNDLE.name)
    state['endpoint'] = args.endpoint
    shutil.copytree(args.backup / 'clients', CLIENTS)
    activate(state)
    print('Xray restored with original keys/clients. Update direct export addresses if the exit IPv4 changed.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name, action in (('install', install), ('restore', restore)):
        sub = commands.add_parser(name)
        sub.add_argument('--endpoint', required=True)
        sub.add_argument('--entry')
        sub.add_argument('--port', type=int, default=443)
        sub.add_argument('--entry-port', type=int, default=443)
        sub.add_argument('--client', default='client1')
        sub.add_argument('--with-awg', action='store_true')
        sub.add_argument('--allow-private-endpoint', action='store_true')
        if name == 'install':
            sub.add_argument('--target')
            sub.add_argument('--check-only', action='store_true')
        else:
            sub.add_argument('--backup', type=Path, required=True)
        sub.set_defaults(action=action)
    sub = commands.add_parser('add-client')
    sub.add_argument('--name', required=True)
    sub.set_defaults(action=add_client)
    sub = commands.add_parser('backup')
    sub.add_argument('--output', type=Path, required=True)
    sub.set_defaults(action=backup)
    args = parser.parse_args()
    try:
        if sys.platform != 'linux' or os.geteuid() != 0:
            raise ValueError('Run on Linux as root')
        os.umask(0o077)
        os.environ.update(DEBIAN_FRONTEND='noninteractive', LC_ALL='C')
        args.action(args)
    except (OSError, ValueError, RuntimeError, KeyError, TypeError):
        print('KIT_ERROR=XRAY_' + getattr(args, 'phase', 'OPERATION'), file=sys.stderr)
        print('Xray operation failed; private state/output suppressed. See docs/xray.md.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
