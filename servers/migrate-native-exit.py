"""Manage a guarded AmneziaWG Docker-to-systemd cutover on B."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from ipaddress import IPv4Address, IPv4Interface, IPv4Network
import fcntl
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time


ROOT = Path('/var/lib/coldwire-native-exit')
STATE = ROOT / 'state.json'
LOCKDOWN = Path('/etc/coldwire-lockdown/active.nft')
UNIT_FILE = Path('/etc/systemd/system/awg-relay-kit-exit.service')
XTABLES_FILE = Path('/etc/tmpfiles.d/coldwire-native-exit.conf')
TOOLS = ROOT / 'bin'
AWG = str(TOOLS / 'awg')
UNIT = 'awg-relay-kit-exit.service'
ROLLBACK = 'coldwire-exit-rollback'
ADMIN = 'coldwire-lockdown-ssh.service'
WAN = 'coldwire-lockdown.service'
CONTAINER = ('docker', 'exec', 'amnezia-awg2')
CFG = '/opt/amnezia/awg/awg0.conf'


def run(*args, data=None):
    if args[0] == 'nft' and shutil.which('nft') is None:
        args = ('/opt/coldwire-lockdown/nft', *args[1:])
    result = subprocess.run(args, input=data, text=True, capture_output=True, timeout=55)
    if result.returncode:
        label = ' '.join(args[:2]) if args[0] in {'docker', 'systemctl'} else Path(args[0]).name
        raise RuntimeError(f'{label} returned {result.returncode}')
    return result.stdout


def ok(*args):
    if args[0] == 'nft' and shutil.which('nft') is None:
        args = ('/opt/coldwire-lockdown/nft', *args[1:])
    return subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=55).returncode == 0


def private(path, value):
    temp = path.with_suffix(path.suffix + '.new')
    with temp.open('w') as out:
        out.write(value)
        out.flush()
        os.fsync(out.fileno())
    temp.replace(path)


@contextmanager
def transaction():
    with (ROOT / 'transaction.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def parse(text):
    interface, peers = {}, {}
    for index, block in enumerate(re.split(r'(?m)^\s*\[Peer\]\s*$', text)):
        fields = {}
        for line in block.splitlines():
            line = line.strip()
            if not line or line.startswith(('#', ';')) or (index == 0 and line == '[Interface]'):
                continue
            key, value = (part.strip() for part in line.split('=', 1))
            if not key or key in fields:
                raise ValueError('Duplicate or invalid AWG field')
            fields[key] = value
        if index:
            peer = fields.pop('PublicKey')
            if peer in peers:
                raise ValueError('Duplicate AWG peer')
            peers[peer] = fields
        else:
            interface = fields
    return interface, peers


def peer_identity(peers):
    return {key: (fields.get('PresharedKey'), frozenset(part.strip() for part in fields.get('AllowedIPs', '').split(',')))
            for key, fields in peers.items()}


def serialize(interface, peers):
    lines = ['[Interface]', *(f'{key} = {value}' for key, value in interface.items())]
    for key, fields in peers.items():
        lines += ['', '[Peer]', f'PublicKey = {key}', *(f'{k} = {v}' for k, v in fields.items())]
    return '\n'.join(lines) + '\n'


def read_state():
    return json.loads(STATE.read_text())


def inspect():
    return json.loads(run('docker', 'inspect', 'amnezia-awg2'))[0]


def status():
    if (ROOT / 'armed').exists():
        return 'pending'
    if (ROOT / 'confirmed').exists():
        return 'native'
    if (ROOT / 'rolled-back').exists():
        return 'docker-restored'
    return 'docker'


def stage(entry):
    entry = IPv4Address(entry)
    os_release = dict(line.split('=', 1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
    if (os_release['ID'].strip('"') != 'ubuntu' or os_release['VERSION_ID'].strip('"') != '22.04'
            or platform.machine() != 'x86_64' or not Path('/dev/net/tun').exists()):
        raise ValueError('Migration requires Ubuntu 22.04 amd64 with TUN available')
    if (status() not in {'docker', 'docker-restored'} or UNIT_FILE.exists() or XTABLES_FILE.exists()
            or ok('systemctl', 'is-active', '--quiet', UNIT)):
        raise ValueError('Another native installation or migration is present')
    confirmed = LOCKDOWN.read_text()
    if (not confirmed or confirmed != LOCKDOWN.with_name('final.nft').read_text()
            or any(LOCKDOWN.with_name(name).exists() for name in ('pending.nft', 'pending.timer'))
            or not ok('systemctl', 'is-active', '--quiet', WAN)):
        raise ValueError('B needs an active, confirmed COLDWIRE firewall')
    wan = json.loads(run('ip', '-j', '-4', 'route', 'get', str(entry)))[0]['dev']
    if not re.fullmatch(r'[a-zA-Z0-9_.-]+', wan):
        raise ValueError('Invalid WAN interface')
    if entry.is_global and {item['dev'] for item in json.loads(run('ip', '-j', '-4', 'route', 'show', 'default'))} != {wan}:
        raise ValueError('B needs one WAN interface for access from A and forwarded Internet traffic')
    obj = inspect()
    bindings = obj['NetworkSettings']['Ports']
    if not obj['State']['Running'] or len(bindings) != 1:
        raise ValueError('Expected one published UDP port on the running container')
    name, endpoints = next(iter(bindings.items()))
    kind = re.fullmatch(r'(\d{1,5})/udp', name)
    ports = {int(item['HostPort']) for item in endpoints if ':' not in item['HostIp']}
    if not kind or len(ports) != 1:
        raise ValueError('Expected one published host IPv4 port')
    port, = ports
    chain = run('nft', '-s', 'list', 'chain', 'inet', 'coldwire_lockdown', 'wan')
    allowed = f'ip saddr {entry} udp dport {port} accept'
    denied = f'udp dport {port} drop'
    if (f'iifname != "{wan}" return' not in confirmed or allowed not in confirmed or denied not in confirmed
            or allowed not in chain or denied not in chain):
        raise ValueError('B must already restrict the published UDP port to A')
    device = json.loads(run(*CONTAINER, 'ip', '-j', 'address', 'show', 'dev', 'awg0'))[0]
    address, = (str(IPv4Interface(f"{entry['local']}/{entry['prefixlen']}")) for entry in device['addr_info']
                if entry['family'] == 'inet')
    on_disk = run(*CONTAINER, 'cat', CFG)
    stripped_if, stripped_peers = parse(run(*CONTAINER, 'awg-quick', 'strip', CFG))
    running_if, running_peers = parse(run(*CONTAINER, 'awg', 'showconf', 'awg0'))
    running_public = run(*CONTAINER, 'awg', 'show', 'awg0', 'public-key').strip()
    disk_public = run('docker', 'exec', '-i', 'amnezia-awg2', 'awg', 'pubkey',
                      data=stripped_if['PrivateKey'] + '\n').strip()
    if disk_public != running_public or int(running_if['ListenPort']) != int(kind[1]):
        raise ValueError('Inconsistent server identity or port')
    live = peer_identity(running_peers)
    disk = peer_identity(stripped_peers)
    if any(live.get(key) != identity for key, identity in disk.items()):
        raise ValueError('Persistent peer absent or different in the running interface')
    pool = IPv4Interface(address).network
    used = set()
    for _, addresses in live.values():
        for allowed_ip in addresses:
            route = IPv4Network(allowed_ip)
            if route.prefixlen != 32 or not route.subnet_of(pool) or route in used:
                raise ValueError('Only unique IPv4 host routes inside the tunnel subnet are supported')
            used.add(route)
    for key, fields in running_peers.items():
        endpoint = stripped_peers.get(key, {}).get('Endpoint')
        if endpoint:
            fields['Endpoint'] = endpoint
        else:
            fields.pop('Endpoint', None)
    restore = serialize(running_if, running_peers)
    native = serialize(running_if | {'ListenPort': str(port)}, running_peers)
    old_policy = obj['HostConfig']['RestartPolicy']
    mode = old_policy['Name'] or 'no'
    if mode == 'on-failure' and old_policy['MaximumRetryCount']:
        mode += ':' + str(old_policy['MaximumRetryCount'])
    expected = {'wan': wan, 'address': address, 'mtu': device['mtu'], 'published': port,
                'inside': int(kind[1]), 'restart': mode, 'container_id': obj['Id'],
                'public': running_public,
                'forwarding': Path('/proc/sys/net/ipv4/ip_forward').read_text().strip(),
                'peers': len(live), 'runtime_only': len(live.keys() - disk.keys())}
    private(ROOT / 'container.conf', on_disk)
    private(ROOT / 'rollback.awg', restore)
    private(ROOT / 'native.awg', native)
    private(ROOT / 'wan.before', confirmed)
    private(STATE, json.dumps(expected))
    print(json.dumps({k: expected[k] for k in ('published', 'inside', 'peers', 'runtime_only')}), flush=True)


def forward_rules(state):
    iface, net = state['wan'], str(IPv4Interface(state['address']).network)
    return (('-i', 'awg0', '-o', iface, '-s', net),
            ('-i', iface, '-o', 'awg0', '-d', net, '-m', 'conntrack', '--ctstate', 'ESTABLISHED,RELATED'))


def up():
    state = read_state()
    for _ in range(300):
        if ok(AWG, 'show', 'awg0', 'public-key'):
            break
        time.sleep(.1)
    else:
        raise RuntimeError('Native AWG control socket did not start')
    run(AWG, 'setconf', 'awg0', str(ROOT / 'native.awg'))
    run('ip', 'address', 'replace', state['address'], 'dev', 'awg0')
    run('ip', 'link', 'set', 'dev', 'awg0', 'mtu', str(state['mtu']), 'up')
    down()
    net = IPv4Interface(state['address']).network
    run('nft', '-f', '-', data=f'''table ip coldwire_native_exit {{
chain postrouting {{ type nat hook postrouting priority srcnat; policy accept;
oifname "{state['wan']}" ip saddr {net} masquerade; }}
}}\n''')
    for spec in forward_rules(state):
        run('iptables', '-w', '5', '-I', 'FORWARD', '1', *spec, '-m', 'comment',
            '--comment', 'coldwire-native-exit', '-j', 'ACCEPT')
    run('sysctl', '-w', 'net.ipv4.ip_forward=1')
    verify('native')


def down():
    ok('nft', 'delete', 'table', 'ip', 'coldwire_native_exit')
    for spec in forward_rules(read_state()):
        ok('iptables', '-w', '5', '-D', 'FORWARD', *spec, '-m', 'comment',
           '--comment', 'coldwire-native-exit', '-j', 'ACCEPT')


def verify(backend):
    state = read_state()
    tool, ref, port = (AWG,), 'native.awg', state['published']
    if backend == 'docker':
        tool, ref, port = CONTAINER + ('awg',), 'rollback.awg', state['inside']
        if inspect()['Id'] != state['container_id'] or run(*CONTAINER, 'cat', CFG) != (ROOT/'container.conf').read_text():
            raise ValueError('Unexpected original container or disk configuration')
    expected_if, expected_peers = parse((ROOT / ref).read_text())
    current_if, current_peers = parse(run(*tool, 'showconf', 'awg0'))
    if (run(*tool, 'show', 'awg0', 'public-key').strip() != state['public'] or int(current_if['ListenPort']) != port
            or expected_if != current_if or peer_identity(expected_peers) != peer_identity(current_peers)):
        raise ValueError('Server parameters or peer identity did not survive the cutover')


def cutover(seconds):
    state = read_state()
    if not 60 <= seconds <= 3600:
        raise ValueError('Rollback timeout must be 60–3600 seconds')
    units = Path('/etc/systemd/system')
    deadline = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    with transaction():
        if status() not in {'docker', 'docker-restored'} or UNIT_FILE.exists() or XTABLES_FILE.exists():
            raise ValueError('Another native installation or migration is present')
        verify('docker')
        (ROOT / 'rolled-back').unlink(missing_ok=True)
        private(units / (ROLLBACK + '.service'), f'''[Unit]
Description=Restore the previous AmneziaWG container
ConditionPathExists={ROOT}/armed
StartLimitIntervalSec=0
[Service]
Type=oneshot
TimeoutStartSec=120
Restart=on-failure
RestartSec=10s
ExecStart=/usr/bin/python3 {__file__} rollback
''')
        private(units / (ROLLBACK + '.timer'), f'''[Unit]
Description=Recover the old exit unless the cutover is confirmed
[Timer]
OnCalendar={deadline.strftime('%Y-%m-%d %H:%M:%S UTC')}
Persistent=true
AccuracySec=1s
[Install]
WantedBy=timers.target
''')
        private(ROOT / 'armed', str(int(deadline.timestamp())))
        run('systemctl', 'daemon-reload')
        run('systemctl', 'enable', '--now', ROLLBACK + '.timer')
        run('systemctl', 'is-active', '--quiet', ROLLBACK + '.timer')
        run('systemctl', 'is-enabled', '--quiet', ROLLBACK + '.timer')
        os.sync()
        private(UNIT_FILE, (ROOT/'native.service').read_text())
        UNIT_FILE.chmod(0o644)
        private(XTABLES_FILE, 'f /run/xtables.lock 0600 root root -\n')
        XTABLES_FILE.chmod(0o644)
        run('systemd-tmpfiles', '--create', XTABLES_FILE.name)
        run('systemctl', 'daemon-reload')
        run('systemd-analyze', 'verify', '--man=no', UNIT)
        private(ROOT / 'cutover-start', str(int(time.time())))
        run('docker', 'update', '--restart=no', 'amnezia-awg2')
        run('docker', 'stop', '--time=5', 'amnezia-awg2')
        if not 1 <= state['published'] <= 65535:
            raise ValueError('Invalid original published port')
        run('systemctl', 'enable', '--now', UNIT)


def rollback():
    state = read_state()
    with transaction():
        armed = ROOT / 'armed'
        if not armed.exists():
            return
        if UNIT_FILE.exists():
            run('systemctl', 'disable', '--now', UNIT)
            UNIT_FILE.unlink()
            run('systemctl', 'daemon-reload')
        XTABLES_FILE.unlink(missing_ok=True)
        down()
        saved = (ROOT / 'wan.before').read_text()
        if not LOCKDOWN.exists() or LOCKDOWN.read_text() != saved:
            private(LOCKDOWN, saved)
            run('systemctl', 'restart', WAN)
        run('systemctl', 'start', WAN, ADMIN, 'docker.service')
        run('docker', 'update', '--restart=' + state['restart'], 'amnezia-awg2')
        run('docker', 'start', 'amnezia-awg2')
        for _ in range(30):
            if ok(*CONTAINER, 'awg', 'show', 'awg0', 'public-key'):
                break
            time.sleep(1)
        run(*CONTAINER[:2], '-i', CONTAINER[2], 'awg', 'syncconf', 'awg0', '/dev/stdin',
            data=(ROOT / 'rollback.awg').read_text())
        run('sysctl', '-w', 'net.ipv4.ip_forward=' + state['forwarding'])
        verify('docker')
        private(ROOT / 'rolled-back', Path('/proc/sys/kernel/random/boot_id').read_text())
        armed.unlink()
        run('systemctl', 'disable', '--now', ROLLBACK + '.timer')
        os.sync()


def confirm():
    with transaction():
        armed = ROOT / 'armed'
        if not armed.exists() or int(time.time()) >= int(armed.read_text()):
            raise ValueError('Cutover deadline expired')
        run('systemctl', 'is-active', '--quiet', UNIT)
        verify('native')
        started = int((ROOT / 'cutover-start').read_text())
        transfers = {key: (int(rx), int(tx)) for key, rx, tx in
                     (line.split() for line in run(AWG, 'show', 'awg0', 'transfer').splitlines())}
        if not any(int(stamp) >= started and min(transfers[key]) > 0 for key, stamp in
                   (line.split() for line in run(AWG, 'show', 'awg0', 'latest-handshakes').splitlines())):
            raise ValueError('No existing peer completed a new handshake and exchanged traffic on B')
        armed.replace(ROOT / 'confirmed')
        run('systemctl', 'disable', '--now', ROLLBACK + '.timer')
        os.sync()


if __name__ == '__main__':
    os.umask(0o077)
    try:
        command, *args = sys.argv[1:]
        if command == 'cutover':
            args = [int(args[0])]
        if command == 'status':
            print(status())
        elif command == 'stage':
            with transaction():
                stage(*args)
        else:
            {'up': up, 'down': down, 'cutover': cutover, 'rollback': rollback,
             'confirm': confirm, 'verify': verify}[command](*args)
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        sys.exit(str(error))
