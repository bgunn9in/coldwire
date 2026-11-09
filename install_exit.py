"""Install native AWG on Ubuntu 22.04/24.04/26.04 LTS or Debian 12/13, without Docker or a compiler."""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile

from exit_config import valid_key, parameters, new_client, server_config, save_state, write_private, public_binary_directory

ROOT = Path(__file__).resolve().parent
STATE = Path('/etc/awg-relay-kit-exit')
CLIENTS = Path('/root/awg-relay-kit-clients')
BIN = Path('/usr/local/libexec/awg-relay-kit')
SERVICE = 'awg-relay-kit-exit.service'
UNIT = Path('/etc/systemd/system') / SERVICE
SYSCTL = Path('/etc/sysctl.d/90-awg-relay-kit-exit.conf')
BUNDLE = ROOT / 'dist/awg-native-linux-amd64.tar.gz'
MARKER = 'awg-relay-kit-native-v1'
GO_COMMIT = '1b86b2ae0e493e7ea93f8c1a0f0cb6735b1551f1'
TOOLS_COMMIT = 'ee0f0a9aa34ff0a0da4b3433b9512781cfe02843'
BUNDLE_SHA256 = '44c066267291dcfbf493725f00d28ce65fd7722097a434927efa18c9e3b90749'
SUPPORTED_RELEASES = {'ubuntu': ('22.04', '24.04', '26.04'), 'debian': ('12', '13')}


def run(*args, data=None, visible=False):
    result = subprocess.run(args, input=data, text=True, capture_output=not visible)
    if result.returncode:
        raise RuntimeError(f'{args[0]} failed (exit {result.returncode}); private input/error was not printed')
    return result.stdout.strip() if result.stdout else ''


def generate_key(kind='genkey'):
    return valid_key(run(str(BIN / 'awg'), kind))


def public_key(private):
    return valid_key(run(str(BIN / 'awg'), 'pubkey', data=private + '\n'))


def read_bundle(path):
    checksum = path.with_suffix('').with_suffix('.sha256').read_text().split()[0]
    if checksum != BUNDLE_SHA256 or hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
        raise ValueError('Native bundle SHA256 mismatch')
    expected = {'awg', 'amneziawg-go', 'manifest.json', 'LICENSE.amneziawg-go', 'COPYING.amneziawg-tools', 'amneziawg-tools-source.tar.gz'}
    with tarfile.open(path, 'r:gz') as archive:
        members = archive.getmembers()
        if len(members) != len(expected) or {m.name for m in members} != expected or any(not m.isfile() or m.size > 32_000_000 for m in members):
            raise ValueError('Unexpected archive contents')
        files = {m.name: archive.extractfile(m).read() for m in members}
    manifest = json.loads(files['manifest.json'])
    if manifest.get('platform') != 'linux-amd64' or manifest.get('awg_go_commit') != GO_COMMIT or manifest.get('awg_tools_commit') != TOOLS_COMMIT:
        raise ValueError('Unexpected native build provenance')
    if set(manifest['files']) != expected - {'manifest.json'}:
        raise ValueError('Incomplete native build manifest')
    if any(hashlib.sha256(files[name]).hexdigest() != digest for name, digest in manifest['files'].items()):
        raise ValueError('Native file hash mismatch')
    return files


def require_supported_host():
    release = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
    version = release.get('VERSION_ID', '').strip('"')
    if version not in SUPPORTED_RELEASES.get(release.get('ID', '').strip('"'), ()):
        raise ValueError('Supported server releases: Ubuntu 22.04, 24.04, 26.04 LTS; Debian 12, 13')
    if platform.machine() != 'x86_64' or not Path('/run/systemd/system').is_dir():
        raise ValueError('Requires amd64 Linux with systemd')
    return version


def preflight(args):
    address = ipaddress.IPv4Address(args.endpoint)
    private_allowed = getattr(args, 'allow_private_endpoint', False) and any(address in ipaddress.IPv4Network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
    if (not address.is_global or address.is_multicast) and not private_allowed:
        raise ValueError('Use a public --endpoint, or explicitly --allow-private-endpoint for a local LAN/VM')
    if args.entry:
        entry = ipaddress.IPv4Address(args.entry)
        private_entry = getattr(args, 'allow_private_endpoint', False) and any(entry in ipaddress.IPv4Network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
        if (not entry.is_global or entry.is_multicast) and not private_entry or args.entry == args.endpoint:
            raise ValueError('--entry must be a different valid IPv4; private addresses require the explicit lab flag')
    if not all(1 <= p <= 65535 for p in (args.port, args.entry_port)):
        raise ValueError('Invalid UDP port')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,47}', args.client):
        raise ValueError('Invalid client name')
    require_supported_host()
    if any(p.exists() for p in (STATE, CLIENTS, BIN, UNIT, SYSCTL, Path('/opt/amnezia'), Path('/etc/awg-relay-kit-xray'))):
        raise ValueError('An exit installation/output already exists; refusing to overwrite')
    if shutil.which('docker') or Path('/var/lib/docker').exists():
        raise ValueError('Existing Docker installation detected; use a clean new VPS')
    assigned = {a['local'] for d in json.loads(run('ip', '-j', 'address')) for a in d['addr_info'] if a['family'] == 'inet'}
    if str(address) not in assigned:
        raise ValueError('--endpoint is not assigned to this server')
    if run('ss', '-H', '-lun', f'sport = :{args.port}'):
        raise ValueError('UDP port is occupied')
    if run('sysctl', '-n', 'net.ipv4.ip_forward') != '0':
        raise ValueError('Existing forwarding detected; use a dedicated clean VPS')
    if shutil.which('ufw') and 'Status: active' in run('ufw', 'status'):
        raise ValueError('Active UFW detected; refusing to change host firewall')
    if shutil.which('nft') and run('nft', 'list', 'tables'):
        raise ValueError('Existing nftables tables detected')
    links = json.loads(run('ip', '-j', '-d', 'link', 'show'))
    if any(d.get('linkinfo', {}).get('info_kind') in {'wireguard', 'amneziawg'} for d in links):
        raise ValueError('Existing VPN interface detected')
    vpn = ipaddress.IPv4Network('10.8.1.0/24')
    routes = json.loads(run('ip', '-j', '-4', 'route', 'show', 'table', 'all'))
    if any(r.get('dst') not in (None, 'default') and ipaddress.IPv4Network(r['dst']).overlaps(vpn) for r in routes):
        raise ValueError('10.8.1.0/24 overlaps an existing host route')


def prepare(files, bundle):
    run('apt-get', 'update', '-o', 'Acquire::Retries=3', visible=True)
    run('apt-get', 'install', '-y', '--no-install-recommends', 'nftables', 'iproute2', 'kmod', visible=True)
    if not Path('/dev/net/tun').exists():
        run('modprobe', 'tun')
    if not Path('/dev/net/tun').exists():
        raise ValueError('TUN is unavailable; enable it at the VPS provider')
    public_binary_directory(BIN)
    for name, content in files.items():
        write_private(BIN / name, content)
        (BIN / name).chmod(0o755 if name in {'awg', 'amneziawg-go'} else 0o644)
    write_private(BIN / 'native-runtime.py', (ROOT / 'servers/native-runtime.py').read_bytes())
    for source in (bundle, bundle.with_suffix('').with_suffix('.sha256')):
        shutil.copy2(source, BIN / source.name)


def nft_rules(interface):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', interface):
        raise ValueError('Invalid WAN interface')
    return f'''table ip awg_exit {{
 chain forward {{
  type filter hook forward priority filter; policy drop;
  ct state invalid drop
  iifname "awg0" oifname "{interface}" ip saddr 10.8.1.0/24 counter accept
  iifname "{interface}" oifname "awg0" ip daddr 10.8.1.0/24 ct state established,related counter accept
 }}
 chain postrouting {{
  type nat hook postrouting priority srcnat; policy accept;
  oifname "{interface}" ip saddr 10.8.1.0/24 counter masquerade
 }}
}}
'''


def service_text(port=32497):
    capabilities = 'CAP_NET_ADMIN' + (' CAP_NET_BIND_SERVICE' if port < 1024 else '')
    return f'''[Unit]
Description=Native AmneziaWG 3.1 exit
Wants=network-online.target
After=network-online.target systemd-sysctl.service nftables.service
[Service]
Type=simple
ExecStart={BIN}/amneziawg-go -f awg0
ExecStartPost=/usr/bin/python3 {BIN}/native-runtime.py up
ExecStopPost=/usr/bin/python3 {BIN}/native-runtime.py down
Restart=on-failure
RestartSec=2
TimeoutStartSec=45
TimeoutStopSec=15
RuntimeDirectory=amneziawg
RuntimeDirectoryMode=0700
UMask=0077
Environment=GOMAXPROCS=1 GOMEMLIMIT=96MiB
CapabilityBoundingSet={capabilities}
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/run/amneziawg
DevicePolicy=closed
DeviceAllow=/dev/net/tun rw
RestrictAddressFamilies=AF_INET AF_INET6 AF_NETLINK AF_UNIX
MemoryAccounting=true
TasksMax=64
[Install]
WantedBy=multi-user.target
'''


def activate(state):
    STATE.mkdir(mode=0o700)
    save_state(STATE, state)
    write_private(STATE / 'exit.nft', nft_rules(state['wan_interface']))
    write_private(UNIT, service_text(state['port']))
    # The service owns forwarding: up enables it after nft, down restores 0.
    run('systemctl', 'daemon-reload')
    try:
        run('systemctl', 'enable', '--now', SERVICE)
        run('systemctl', 'is-active', '--quiet', SERVICE)
        if run(str(BIN / 'awg'), 'show', 'awg0', 'public-key') != state['public_key']:
            raise RuntimeError('Unexpected server key after activation')
        if set(run(str(BIN / 'awg'), 'show', 'awg0', 'peers').split()) != {c['public_key'] for c in state['clients'].values()}:
            raise RuntimeError('Peer registration verification failed')
    except BaseException:
        try:
            run('systemctl', 'disable', '--now', SERVICE)
        finally:
            SYSCTL.unlink(missing_ok=True)
            run('sysctl', '-w', 'net.ipv4.ip_forward=0')
        print('Service stopped after failed activation; private files retained for inspection.', file=sys.stderr)
        raise


def install(args):
    preflight(args)
    if getattr(args, 'check_only', False):
        print('Exit preflight passed; no installation performed')
        return
    files = read_bundle(BUNDLE)
    prepare(files, BUNDLE)
    private = generate_key()
    interface = json.loads(run('ip', '-j', 'route', 'get', '1.1.1.1'))[0]['dev']
    state = {'installer': MARKER, 'endpoint': args.endpoint, 'port': args.port, 'entry': args.entry,
             'entry_port': args.entry_port, 'wan_interface': interface, 'private_key': private,
             'public_key': public_key(private), 'psk': generate_key('genpsk'), 'parameters': parameters(generate_key()), 'clients': {}}
    private = generate_key()
    state, exports = new_client(state, args.client, private, public_key(private))
    CLIENTS.mkdir(mode=0o700)
    folder = CLIENTS / args.client
    folder.mkdir(mode=0o700)
    for name, content in exports.items():
        write_private(folder / name, content)
    activate(state)
    print(f'Native AWG 3.1 ready: {args.endpoint}:{args.port}/UDP. Secret client profiles: {folder}')


def load_owned():
    if not STATE.is_dir() or (STATE / 'server.json').is_symlink():
        raise ValueError('No native kit-managed installation')
    state = json.loads((STATE / 'server.json').read_text())
    if state.get('installer') != MARKER or (STATE / 'awg0.conf').read_text() != server_config(state):
        raise ValueError('Wrong installation type or inconsistent persistent config')
    return state


def issue_client(previous, changed, files, name):
    folder = CLIENTS / name
    folder.mkdir(mode=0o700)
    client = changed['clients'][name]
    try:
        for filename, content in files.items():
            write_private(folder / filename, content)
        save_state(STATE, changed)
        run(str(BIN / 'awg'), 'set', 'awg0', 'peer', client['public_key'], 'preshared-key', '/dev/stdin',
            'allowed-ips', client['address'] + '/32', data=changed['psk'] + '\n')
    except BaseException:
        save_state(STATE, previous)
        try:
            run(str(BIN / 'awg'), 'set', 'awg0', 'peer', client['public_key'], 'remove')
        except RuntimeError:
            print('New runtime peer removal failed; inspect locally before retrying.', file=sys.stderr)
        print('Client issue failed; old persistent config restored. Partial exports retained privately.', file=sys.stderr)
        raise


def add_client(args):
    import fcntl
    if not STATE.is_dir():
        raise ValueError('No native exit installation')
    with (STATE / 'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = load_owned()
        if run(str(BIN / 'awg'), 'show', 'awg0', 'public-key') != state['public_key']:
            raise ValueError('Runtime server key differs from saved state')
        private = generate_key()
        changed, files = new_client(state, args.name, private, public_key(private))
        issue_client(state, changed, files, args.name)
    print(f'Peer added without restarting AWG; private exports: {CLIENTS / args.name}')


def backup(args):
    import fcntl
    if not STATE.is_dir():
        raise ValueError('No native exit installation')
    with (STATE / 'lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        load_owned()
        args.output.mkdir(mode=0o700)
        shutil.copytree(STATE, args.output / 'state')
        shutil.copytree(CLIENTS, args.output / 'clients')
        package = BIN / BUNDLE.name
        for source in (package, package.with_suffix('').with_suffix('.sha256')):
            shutil.copy2(source, args.output / source.name)
    print('Secret backup created:', args.output)


def restore(args):
    saved = args.backup / 'state'
    state = json.loads((saved / 'server.json').read_text())
    if state.get('installer') != MARKER or (saved / 'awg0.conf').read_text() != server_config(state):
        raise ValueError('Invalid native backup')
    args.port = state['port']
    args.entry, args.entry_port = state.get('entry'), state['entry_port']
    args.client = 'restored'
    preflight(args)
    package = args.backup / BUNDLE.name
    prepare(read_bundle(package), package)
    state['endpoint'] = args.endpoint
    state['wan_interface'] = json.loads(run('ip', '-j', 'route', 'get', '1.1.1.1'))[0]['dev']
    shutil.copytree(args.backup / 'clients', CLIENTS)
    activate(state)
    print('Native exit restored. Old direct exports need an Endpoint update if the server IP changed.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name, action in (('install', install), ('restore', restore)):
        sub = commands.add_parser(name)
        sub.add_argument('--endpoint', required=True)
        sub.add_argument('--allow-private-endpoint', action='store_true', help='Explicit opt-in for local RFC1918 LAN/VM testing')
        sub.add_argument('--port', type=int, default=32497)
        sub.add_argument('--entry')
        sub.add_argument('--entry-port', type=int, default=32497)
        sub.add_argument('--client', default='client1')
        if name == 'install':
            sub.add_argument('--check-only', action='store_true')
        if name == 'restore':
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
        os.environ['DEBIAN_FRONTEND'] = 'noninteractive'
        os.environ['LC_ALL'] = 'C'
        args.action(args)
    except (OSError, ValueError, RuntimeError) as error:
        print('Operation failed: ' + str(error), file=sys.stderr)
        return 1
    except (KeyError, TypeError):
        print('Operation failed: unexpected private state schema; state was not printed.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
