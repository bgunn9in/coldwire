#!/usr/bin/env python3
"""Install SPA and a private SSH path, or manage an installed COLDWIRE relay."""

import argparse
from contextlib import ExitStack, contextmanager
from getpass import getpass
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zlib

import paramiko

from convert_profile import awg_section, client_config, convert, decode, encode
from deploy import ROOT, DeployError, Remote, Server, deploy, probe_relay, validate_address
from exit_config import replace_private, valid_key, write_private
import create_backup
import exit_migration
import legacy_profiles
import restore_backup
import update_lists
from servers.lockdown_rules import admission_gate, firewall
from servers.spa_access import key_bytes, request


CONFIG = '/etc/coldwire-lockdown'
TOOLS = '/opt/coldwire-lockdown'
STAGE = f'bash {TOOLS}/stage-lockdown.sh'
LIVE_TABLE = (f'if command -v nft >/dev/null; then nft list table inet coldwire_lockdown; '
              f'else {TOOLS}/nft list table inet coldwire_lockdown; fi')
SPA = '/etc/coldwire-access/spa-keys.json'
PILOT_SPA = 'coldwire-spa-pilot.service'
PILOT_KEYS = CONFIG + '/pilot-keys.json'
NATIVE = 'python3 /opt/awg-relay-kit/install_exit.py'
NATIVE_AWG = '/usr/local/libexec/awg-relay-kit/awg'
DEFAULT_PORT = 32497
SPA_PORT = 62201
NAME = re.compile(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,47}')
PANEL_ERRORS = (OSError, ValueError, DeployError, KeyError, paramiko.SSHException, zlib.error)
RECOVERY_ERRORS = (OSError, ValueError, KeyError, EOFError, tarfile.TarError)


def read_server(role, args):
    supplied = getattr(args, role)
    address, _, port = (supplied or input(f'{role} IPv4[:SSH port]: ').strip()).partition(':')
    address = validate_address(address, args.allow_private_endpoint)
    port = int(port or '22')
    user = getattr(args, role + '_user') or input(f'{role} SSH login [root]: ').strip() or 'root'
    password = os.environ.get('AWG_' + role.upper() + '_PASSWORD')
    if password is None:
        password = getpass(f'{role} SSH password: ')
    if not 1 <= port <= 65535 or not NAME.fullmatch(user) or not password or any(c in password for c in '\r\n\0'):
        raise ValueError('Invalid address, port, SSH login or password')
    return Server(role, address, address, port, user, password, password)


def put(remote, filename, body, mode=0o600):
    parent = remote.run('mktemp -d /tmp/coldwire-file-XXXXXXXX', privileged=False).decode().strip()
    if not re.fullmatch(r'/tmp/coldwire-file-[A-Za-z0-9]+', parent):
        raise DeployError('Unexpected staging directory')
    source = parent + '/payload'
    try:
        with remote.sftp.open(source, 'wb') as stream:
            remote.sftp.chmod(source, 0o600)
            stream.write(body.encode() if isinstance(body, str) else body)
        target = shlex.quote(filename)
        remote.run(f'install -m {mode:o} {source} {target}.new && mv -T {target}.new {target}')
    finally:
        remote.run(f'rm -f {source}; rmdir {parent}', privileged=False, check=False)


def install_file(remote, name, directory, mode=0o644):
    data = (ROOT / 'servers' / name).read_bytes().replace(b'\r\n', b'\n')
    put(remote, f'{directory}/{name}', data, mode)


def connect(entry, exit_server, known_hosts, accept_new=False):
    with ExitStack() as cleanup:
        a = Remote(entry, known_hosts, accept_new, check_sudo=bool(entry.password))
        cleanup.callback(a.close)
        path = a.transport.open_channel('direct-tcpip', (exit_server.host, exit_server.port), ('127.0.0.1', 0), timeout=10)
        b = Remote(exit_server, known_hosts, accept_new, connection=path, check_sudo=bool(exit_server.password))
        cleanup.callback(b.close)
        return a, b, cleanup.pop_all()


def route(remote, subnet):
    return json.loads(remote.run(f'ip -j -4 route get {subnet}'))[0]


def fingerprint(remote):
    return remote.run("ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub | cut -d ' ' -f 2").decode().strip()


def ssh_listener(remote, port, operator_public, target=None):
    user = remote.server.username
    forwarding = f'AllowTcpForwarding local\nPermitOpen {target}\n' if target else 'DisableForwarding yes\n'
    put(remote, '/etc/ssh/coldwire_authorized_keys', operator_public, 0o644)
    put(remote, CONFIG + '/sshd.conf', f'''Port {port}
AddressFamily inet
HostKey /etc/ssh/ssh_host_ed25519_key
AuthorizedKeysFile /etc/ssh/coldwire_authorized_keys
AllowUsers {user}
AuthenticationMethods publickey
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
AllowAgentForwarding no
X11Forwarding no
PermitTunnel no
UsePAM yes
Subsystem sftp internal-sftp
{forwarding}''')
    install_file(remote, 'coldwire-lockdown-ssh.service', '/etc/systemd/system')
    remote.run(f'sshd -t -f {CONFIG}/sshd.conf; systemctl daemon-reload')


def setup_firewall(remote, preparation, final):
    remote.run(f'install -d -m 700 {CONFIG} {TOOLS} /etc/coldwire-access /opt/coldwire-access')
    install_file(remote, 'stage-lockdown.sh', TOOLS, 0o700)
    install_file(remote, 'coldwire-lockdown.service', '/etc/systemd/system')
    put(remote, CONFIG + '/stage.nft', preparation)
    put(remote, CONFIG + '/final.nft', final)
    remote.run('systemctl daemon-reload')


def protect_startup(remote):
    lockdown = 'coldwire-lockdown.service'
    ssh = ('ssh.service', 'ssh.socket')
    if remote.server.role == 'entry':
        groups = (
            (lockdown, ssh),
            (lockdown + ' coldwire-access-firewall.service',
             ('coldwire-lockdown-ssh.service', 'coldwire-spa.service', 'blackice-relay.service')),
        )
    else:
        groups = ((lockdown, ssh + ('coldwire-lockdown-ssh.service', 'awg-relay-kit-exit.service')),)
    remote.run(f'systemctl start {lockdown}')
    for dependencies, units in groups:
        dropin = f'[Unit]\nRequires={dependencies}\nAfter={dependencies}\n'
        for unit in units:
            directory = f'/etc/systemd/system/{unit}.d'
            remote.run(f'install -d -m 755 {directory}')
            put(remote, f'{directory}/40-coldwire-firewall.conf', dropin, 0o644)
    remote.run('systemctl daemon-reload')


def choose_ssh(remote):
    for port in range(22222, 22254):
        if not remote.run(f'ss -H -ltn "sport = :{port}"'):
            return port
    raise DeployError(remote.server.role + ': no free management port')


def spa_binary():
    bundled = ROOT / 'dist/coldwire-spa-linux-amd64'
    if bundled.is_file():
        return bundled.read_bytes()
    go = shutil.which('go')
    if not go:
        raise DeployError('The installer needs the bundled SPA executable or Go on the operator computer')
    cache = ROOT / 'cache/coldwire-spa-lockdown-linux-amd64'
    cache.parent.mkdir(exist_ok=True)
    subprocess.run([go, 'build', '-trimpath', '-buildvcs=false', '-ldflags', '-s -w', '-o', cache, '.'],
                   env=dict(os.environ, GOOS='linux', GOARCH='amd64', CGO_ENABLED='0'), cwd=ROOT / 'servers/spa', check=True)
    return cache.read_bytes()


def register_file(entry, config, unit='coldwire-spa.service', destination=SPA):
    previous = entry.run(f'cat {destination}')
    keys = [key_bytes(value) for value in config['devices'] + config.get('admins', [])]
    if not 1 <= len(keys) <= 4096 or len(set(keys)) != len(keys):
        raise ValueError('Invalid number or duplicate SPA keys')
    restart = f'systemctl restart {unit}; systemctl is-active --quiet {unit}'
    if unit == PILOT_SPA:
        restart += '; systemctl start coldwire-lockdown-ssh.service'
    put(entry, destination, json.dumps(config, indent=2) + '\n')
    try:
        entry.run(restart)
    except BaseException:
        put(entry, destination, previous)
        entry.run(restart)
        raise


def admit(address, port, secret):
    for attempt in range(5):
        try:
            request(address, port, key_bytes(secret))
            return
        except (TimeoutError, ConnectionRefusedError):
            if attempt == 4:
                raise
            time.sleep(0.4)


def setup_spa(entry, bind, gate, config, binary):
    for name in ('stage-access.sh',):
        install_file(entry, name, '/opt/coldwire-access')
    install_file(entry, 'coldwire-access-firewall.service', '/etc/systemd/system')
    put(entry, '/etc/coldwire-access/active.nft', gate)
    entry.run('systemctl daemon-reload; systemctl enable --now coldwire-access-firewall.service')
    put(entry, SPA, json.dumps(config, indent=2) + '\n')
    put(entry, '/opt/coldwire-access/coldwire-spa', binary, 0o755)
    put(entry, '/etc/coldwire-access/spa.env', f'CW_SPA_BIND={bind}\nCW_SPA_PORT={SPA_PORT}\n')
    install_file(entry, 'coldwire-spa.service', '/etc/systemd/system')
    entry.run('systemctl daemon-reload; systemctl enable --now coldwire-spa.service')


@contextmanager
def authorized(manifest, folder, bootstrap=None):
    endpoints = [Server(item['role'], item['host'], item['host'], item['port'], item['user'],
                        bootstrap[index].password if bootstrap else '', bootstrap[index].sudo_password if bootstrap else '',
                        item['fingerprint'], folder / 'ssh') for index, item in enumerate(manifest['ssh'])]
    admit(endpoints[0].host, manifest['spa_port'], (folder / 'admin.key').read_text().strip())
    a, b, stack = connect(*endpoints, folder / 'known_hosts', True)
    with stack:
        if not bootstrap:
            for remote in (a, b):
                if remote.needs_sudo_password:
                    remote.server.sudo_password = getpass(remote.server.role + ' sudo password: ')
        yield a, b


def finish_install(manifest, folder, bootstrap=None):
    with authorized(manifest, folder, bootstrap) as (new_a, new_b):
        for node in (new_a, new_b):
            node.run('test "$(id -u)" = 0')
        for node in (new_b, new_a):
            node.run(f'{STAGE} confirm')
    with authorized(manifest, folder, bootstrap) as (new_a, new_b):
        for node in (new_b, new_a):
            node.run(f'{STAGE} stage {CONFIG}/final.nft')
    with authorized(manifest, folder, bootstrap) as (new_a, new_b):
        address, port = manifest['ssh'][0]['host'], manifest['awg_port']
        new_b.run(f'python3 {TOOLS}/spa_access.py request {address} {CONFIG}/probe.key')
        probe_relay(new_b, address, port)
        new_b.run(f'rm -f {CONFIG}/probe.key')
        for node in (new_a, new_b):
            node.run(f'{STAGE} confirm')
        for node in (new_a, new_b):
            protect_startup(node)


def install(args):
    folder = args.folder.resolve()
    if (folder / 'operator.json').is_file():
        manifest = json.loads((folder / 'operator.json').read_text())
        with authorized(manifest, folder) as (a, b):
            for node in (a, b):
                node.run(f'test ! -e {CONFIG}/pending.nft; cmp -s {CONFIG}/active.nft {CONFIG}/final.nft; {LIVE_TABLE}')
        print('Existing installation verified. Use the manage or ssh command.')
        return
    binary = spa_binary()
    first, second = (read_server(role, args) for role in ('entry', 'exit'))
    if first.address == second.address:
        raise ValueError('Use two different servers')
    folder.mkdir(parents=True, mode=0o700)
    subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(folder / 'ssh')], check=True)
    admin = secrets.token_hex(32)
    device = secrets.token_hex(32)
    write_private(folder / 'admin.key', admin + '\n')
    config = {'cookie_key': secrets.token_hex(32), 'devices': [device], 'admins': [admin]}
    known = folder / 'known_hosts'
    with ExitStack() as stack:
        a = Remote(first, known, not args.strict_host_keys)
        stack.callback(a.close)
        b = Remote(second, known, not args.strict_host_keys)
        stack.callback(b.close)
        if a.run('cat /etc/machine-id') == b.run('cat /etc/machine-id'):
            raise DeployError('Both addresses resolve to the same server')
        a_path, b_path = route(a, second.address), route(b, first.address)
        a_ip = str(ipaddress.IPv4Address(a_path['prefsrc']))
        if a_ip != first.address:
            raise DeployError('Entry route toward the exit uses a different source address')
        if args.strict_host_keys:
            print('Both bootstrap SSH identities verified.')
        deploy(a, b, folder / 'native', DEFAULT_PORT, args.allow_private_endpoint)
        first_port, second_port = choose_ssh(a), choose_ssh(b)
        for remote, path, peer, port in ((a, a_path, second.address, first_port), (b, b_path, a_ip, second_port)):
            role = remote.server.role
            rules = (role, path['dev'], peer, DEFAULT_PORT, port)
            setup_firewall(remote, firewall(*rules, retain_ssh=remote.server.port, retain_awg=True), firewall(*rules))
            ssh_listener(remote, port, (folder / 'ssh.pub').read_bytes(),
                         f'{second.address}:{second_port}' if role == 'entry' else None)
        manifest = {'spa_port': SPA_PORT, 'awg_port': DEFAULT_PORT, 'ssh': [
            {'role': remote.server.role, 'host': remote.server.address, 'user': remote.server.username,
             'port': port, 'fingerprint': fingerprint(remote)} for remote, port in ((a, first_port), (b, second_port))]}
        write_private(folder / 'operator.json', json.dumps(manifest, indent=2) + '\n')
        profile = decode((folder / 'native/client.vpn').read_bytes())
        write_private(folder / 'client1.vpn', encode(convert(profile, first.address, DEFAULT_PORT, spa_key=device)))
        write_private(folder / 'devices.json', json.dumps({'client1': {'user': 'client1', 'spa': device}}) + '\n')
        install_file(b, 'spa_access.py', TOOLS)
        put(b, CONFIG + '/probe.key', device + '\n')
        for node in (a, b):
            node.run(f'{STAGE} stage {CONFIG}/stage.nft; systemctl enable --now coldwire-lockdown-ssh.service')
        setup_spa(a, a_ip, admission_gate(a_path['dev'], a_ip, DEFAULT_PORT), config, binary)
        admit(first.address, SPA_PORT, device)
        finish_install(manifest, folder, (first, second))
    print('Installation complete. Client profile and operator keys:', folder)


def load_devices(path):
    return {name: {'user': name, 'spa': value} if isinstance(value, str) else value
            for name, value in json.loads(path.read_text()).items()}


def panel_backends(manifest):
    legacy = manifest.get('legacy_exit', False)
    pilot = manifest.get('pilot_spa', legacy)
    if type(pilot) is not bool:
        raise ValueError('pilot_spa must be a boolean')
    native = manifest.get('native_exit')
    if native is not None and (
        not isinstance(native, dict) or set(native) != {'awg', 'config'} or
        any(not isinstance(path, str) or not re.fullmatch(r'/[A-Za-z0-9._/-]+', path)
            or '..' in path.split('/') for path in native.values())
    ):
        raise ValueError('native_exit needs absolute Linux paths for awg and config')
    unit, keyfile = (PILOT_SPA, PILOT_KEYS) if pilot else ('coldwire-spa.service', SPA)
    return legacy or native is not None, native, unit, keyfile


def manage(args):
    folder = args.folder.resolve()
    registry = folder / 'devices.json'
    command = args.action or input('1 Add device, 2 revoke device, 3 list devices, 4 revoke user: ').strip()
    action = {'1': 'add', '2': 'revoke', '3': 'list', '4': 'revoke-user'}.get(command, command)
    devices = load_devices(registry)
    if action == 'list':
        for name, record in sorted(devices.items(), key=lambda pair: (pair[1]['user'], pair[0])):
            print(record['user'], name)
        return
    if action not in ('add', 'revoke', 'revoke-user'):
        raise ValueError('Choose add, revoke, revoke-user or list')
    name = args.name or input('User name: ' if action == 'revoke-user' else 'Device name: ').strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,47}', name):
        raise ValueError('Use 1–48 ASCII letters, digits, _ or -')
    user = getattr(args, 'user', None) or name
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,47}', user):
        raise ValueError('Use the same character set for user and device names')
    manifest = json.loads((folder / 'operator.json').read_text())
    first = manifest['ssh'][0]
    existing, native, unit, keyfile = panel_backends(manifest)
    with authorized(manifest, folder) as (a, b):
        config = json.loads(a.run(f'cat {keyfile}'))
        if action == 'add':
            output = folder / (name + '.vpn')
            if name in devices or output.exists():
                raise ValueError('Device name or output profile already exists')
            device = secrets.token_hex(32)
            config['devices'].append(device)
            if existing:
                profile, public = legacy_profiles.add(b, put, (folder / 'legacy-template.vpn').read_bytes(), native=native)
            else:
                b.run(f'{NATIVE} add-client --name {name}')
                profile = decode(b.run(f'cat /root/awg-relay-kit-clients/{name}/client.vpn'))
                public = client_config(awg_section(profile))['client_pub_key']
            written = False
            try:
                profile['description'] = name
                result = encode(convert(profile, first['host'], manifest['awg_port'], spa_key=device, spa_port=manifest['spa_port']))
                register_file(a, config, unit, keyfile)
                write_private(output, result)
                written = True
                devices[name] = {'user': user, 'spa': device, 'peer': public}
                replace_private(registry, json.dumps(devices, indent=2) + '\n')
            except BaseException:
                try:
                    if existing:
                        legacy_profiles.revoke(b, put, public, native=native)
                    else:
                        b.run(f'{NATIVE} remove-client --name {name}')
                finally:
                    config['devices'].remove(device)
                    try:
                        register_file(a, config, unit, keyfile)
                    finally:
                        if written:
                            output.unlink(missing_ok=True)
                raise
        elif action in ('revoke', 'revoke-user'):
            names = [name] if action == 'revoke' else [device for device, record in devices.items() if record['user'] == name]
            if not names or any(device not in devices for device in names):
                raise ValueError('No such device or user')
            for device in names:
                if existing:
                    legacy_profiles.revoke(b, put, devices[device]['peer'], native=native)
                else:
                    peer_name = devices[device].get('native_name', device)
                    b.run(f'{NATIVE} remove-client --name {shlex.quote(peer_name)}')
            keys = {devices[device]['spa'] for device in names}
            config['devices'] = [key for key in config['devices'] if key not in keys]
            register_file(a, config, unit, keyfile)
            for device in names:
                (folder / (device + '.vpn')).unlink(missing_ok=True)
                del devices[device]
            replace_private(registry, json.dumps(devices, indent=2) + '\n')
    print(action, name)


def import_profile(args):
    folder = args.folder.resolve()
    manifest = json.loads((folder / 'operator.json').read_text())
    registry = folder / 'devices.json'
    devices = load_devices(registry)
    source = args.source or Path(input('AmneziaVPN .vpn file: ').strip().strip('"'))
    name = args.name or input('Device name: ').strip()
    user = args.user or name
    if not all(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,47}', value) for value in (name, user)):
        raise ValueError('Use 1–48 ASCII letters, digits, _ or - for device and user names')
    output = args.output or (folder / (name + '-coldwire.vpn'))
    if output.exists():
        raise ValueError('The output file already exists')
    try:
        original = decode(source.expanduser().read_bytes())
        awg = awg_section(original)
        donor_path = args.client_profile
        if not donor_path and not awg.get('last_config') and {'userName', 'password', 'sshKey'} & original.keys():
            if args.source is None:
                donor_path = Path(input('Matching client .vpn file: ').strip().strip('"'))
        donor = decode(donor_path.expanduser().read_bytes()) if donor_path else None
        client = client_config(awg_section(donor if donor is not None else original))
        public = valid_key(client['client_pub_key'])
        server_key = valid_key(client['server_pub_key'])
        tunnel = f'{ipaddress.IPv4Address(client["client_ip"])}/32'
    except (ValueError, TypeError, AttributeError, KeyError, zlib.error):
        raise ValueError('Unsupported AmneziaWG profile. An administrator export without client data needs its matching client .vpn.') from None
    existing, native, unit, keyfile = panel_backends(manifest)
    backend = legacy_profiles.awg_command(native) if existing else NATIVE_AWG
    with authorized(manifest, folder) as (a, b):
        if b.run(f'{backend} show awg0 public-key').decode().strip() != server_key:
            raise ValueError('The profile belongs to a different exit server')
        allowed = dict(line.split(maxsplit=1) for line in b.run(f'{backend} show awg0 allowed-ips').decode().splitlines())
        if tunnel not in allowed.get(public, '').replace(',', ' ').split():
            raise ValueError('The profile peer or its tunnel IP is missing from the exit server')
        native_name = None
        if native:
            _, peers = legacy_profiles.blocks(legacy_profiles.read_config(b, native))
            if not any(legacy_profiles.fields(peer)['PublicKey'] == public for peer in peers):
                raise ValueError('The exit has no persistent registration for this peer')
        elif not existing:
            script = ('import json; s=json.load(open("/etc/awg-relay-kit-exit/server.json")); '
                      'print(json.dumps({v["public_key"]:n for n,v in s["clients"].items()}))')
            native_name = json.loads(b.run('python3 -c ' + shlex.quote(script))).get(public)
            if not native_name:
                raise ValueError('The exit has no persistent registration for this peer')
        labels = [label for label, device in devices.items() if device.get('peer') == public or
                  (native_name and device.get('native_name', label) == native_name)]
        if labels and labels != [name]:
            raise ValueError(f'This peer is already registered as {labels[0]}. Use that device name to export another copy.')
        record = devices.get(name)
        if record is not None and name not in labels:
            raise ValueError('The device name belongs to a different peer')
        config = json.loads(a.run(f'cat {keyfile}'))
        device = record['spa'] if record else secrets.token_hex(32)
        if record and device not in config['devices']:
            raise ValueError('The device SPA key has been revoked')
        payload = encode(convert(original, manifest['ssh'][0]['host'], manifest['awg_port'], donor, device, manifest['spa_port']))
        output = output.expanduser().resolve()
        write_private(output, payload)
        try:
            if record is None:
                config['devices'].append(device)
                register_file(a, config, unit, keyfile)
                devices[name] = {'user': user, 'spa': device, 'peer': public}
                if native_name:
                    devices[name]['native_name'] = native_name
                try:
                    replace_private(registry, json.dumps(devices, indent=2) + '\n')
                except BaseException:
                    config['devices'].remove(device)
                    register_file(a, config, unit, keyfile)
                    raise
        except BaseException:
            output.unlink(missing_ok=True)
            raise
    print('COLDWIRE profile:', output)


def ssh(args):
    folder = args.folder.resolve()
    manifest = json.loads((folder / 'operator.json').read_text())
    a, b = manifest['ssh']
    if args.node == 'exit':
        node = b
        jump = ['-J', 'entry']
    else:
        node = a
        jump = []
    executable = shutil.which('ssh')
    if executable is None:
        raise DeployError('OpenSSH client is required on the operator computer')
    with tempfile.TemporaryDirectory(prefix='ssh-config-', dir=folder) as scratch:
        config = Path(scratch) / 'config'
        lines = ['Host *\n  IdentityFile ssh\n  UserKnownHostsFile known_hosts\n  IdentitiesOnly yes\n  StrictHostKeyChecking yes\n']
        for item in (a, b):
            lines.append(f'Host {item["role"]}\n  HostName {item["host"]}\n  Port {item["port"]}\n  User {item["user"]}\n')
        write_private(config, '\n'.join(lines))
        admit(a['host'], manifest['spa_port'], (folder / 'admin.key').read_text().strip())
        return subprocess.call([executable, '-F', config.relative_to(folder).as_posix(), *jump,
                                node['role'], *args.remote_command], cwd=folder)


def status(args):
    folder = args.folder.resolve()
    manifest = json.loads((folder / 'operator.json').read_text())
    with authorized(manifest, folder) as nodes:
        for node in nodes:
            running = node.run('systemctl is-active coldwire-lockdown-ssh.service').decode().strip()
            loaded, _ = node.run(LIVE_TABLE, check=False)
            code, _ = node.run(f'test ! -e {CONFIG}/pending.nft; cmp -s {CONFIG}/active.nft {CONFIG}/final.nft', check=False)
            firewall_state = 'missing' if loaded else ('confirmed' if code == 0 else 'staged')
            print(f'{node.server.role.upper()} {node.server.host}:{node.server.port} | SSH {running} | '
                  f'firewall {firewall_state}')
    print('Operator files:', folder)


def migrate_exit(args):
    folder = args.folder.resolve()
    operator = folder / 'operator.json'
    manifest = json.loads(operator.read_text())
    existing, native, unit, _ = panel_backends(manifest)
    if not existing or unit != PILOT_SPA:
        raise ValueError('This migration is for a Docker exit with pilot SPA on A')
    if args.action == 'stage' and (native is not None or not 60 <= args.timeout <= 3600):
        raise ValueError('Stage needs a Docker operator configuration and a timeout of 60–3600 seconds')
    with authorized(manifest, folder) as (a, b):
        if args.action == 'stage':
            entry = ipaddress.IPv4Address(manifest['ssh'][0]['host'])
            a.run(f'systemctl is-active --quiet {PILOT_SPA}')
            exit_migration.stage(entry, b, folder, args.timeout, put)
            return
        current = exit_migration.state(b)
        if args.action == 'status':
            print(f'B: {current}. Panel: {"native" if native else "docker"}.')
        elif args.action == 'rollback':
            if current != 'pending':
                raise ValueError('Only a pending migration can be rolled back')
            b.run(f'{exit_migration.DRIVER} rollback', timeout=150)
            print('B restored the original Docker service. The panel still uses Docker.')
        else:
            if current == 'pending':
                b.run(f'{exit_migration.DRIVER} confirm', timeout=50)
            elif current != 'native':
                raise ValueError('B has no native migration to confirm')
            b.run('systemctl is-active --quiet awg-relay-kit-exit.service')
            updated = manifest | {'legacy_exit': False, 'pilot_spa': True, 'native_exit': exit_migration.NATIVE_EXIT}
            if updated != manifest:
                replace_private(operator, json.dumps(updated, indent=2) + '\n')
            print('Native B confirmed. The panel uses native peers through pilot SPA on A.')


def migration_menu(folder):
    actions = {
        '1': ('status', None),
        '2': ('stage', 'Switch B to native AmneziaWG and arm the 10-minute rollback? [y/N] '),
        '3': ('confirm', 'Have you verified SSH and your existing VPN profile? [y/N] '),
        '4': ('rollback', 'Restore the Docker exit now? [y/N] '),
    }
    while True:
        print('\nExit migration\n1 Migration status\n2 Start migration\n3 Confirm migration\n4 Roll back\n0 Back')
        try:
            choice = input('> ').strip()
            if choice == '0':
                return
            if choice in actions:
                action, question = actions[choice]
                if question is None or input(question).strip().lower() in {'y', 'yes'}:
                    migrate_exit(argparse.Namespace(folder=folder, action=action, timeout=600))
        except EOFError:
            return
        except PANEL_ERRORS as error:
            print(f'COLDWIRE: {error}', file=sys.stderr)


def restore_action(args):
    if args.action == 'operator' and args.to is None:
        args.to = args.folder
    if args.action != 'check' and args.to is None:
        raise ValueError('Use --to to choose a new destination')
    return restore_backup.recover(args)


def backup_action(args):
    archive, key = create_backup.create(args.folder.resolve(), args.to, args.portable_key, authorized)
    print(f'Backup verified and saved to {archive}')
    print(f'Recovery key saved to {key}')


def recovery_menu():
    actions = {'1': 'check', '2': 'operator', '3': 'export-nodes', '4': 'portable-key'}
    base = restore_backup.data_home()
    while True:
        print('\nRestore from backup\n1 Check backup\n2 Restore operator folder\n'
              '3 Export A and B for recovery\n4 Save a portable recovery key\n0 Back')
        try:
            choice = input('> ').strip()
            if choice == '0':
                return
            if choice not in actions:
                continue
            archive = input('Backup file (Enter for most recent local backup): ').strip().strip('"')
            if archive:
                backup = Path(archive).expanduser()
            else:
                backup = max((base / 'backups').glob('*.cwbackup'), key=lambda p: p.stat().st_mtime_ns, default=None)
                if backup is None:
                    raise ValueError('No local .cwbackup file found. Enter its path')
                print(f'Using {backup}')
            key = input('Key file (Enter for the matching local key): ').strip().strip('"')
            action = actions[choice]
            destination = None
            if action != 'check':
                if action in ('operator', 'export-nodes'):
                    print('Recovery files contain private keys. Choose a new folder on a private local disk.')
                path = input('New destination path: ').strip().strip('"')
                if not path:
                    continue
                destination = Path(path)
            restore_action(argparse.Namespace(action=action, backup=backup, to=destination,
                                              key=Path(key).expanduser() if key else None))
        except (EOFError, KeyboardInterrupt):
            return
        except RECOVERY_ERRORS as error:
            print(f'COLDWIRE: {error}', file=sys.stderr)


def panel(args):
    operator = args.folder / 'operator.json'
    while not operator.is_file():
        print('\nCOLDWIRE\n1 Install COLDWIRE\n10 Restore from backup\n12 Update split-tunneling lists\n0 Exit')
        try:
            choice = input('> ').strip()
        except EOFError:
            return
        if choice == '0':
            return
        if choice == '1':
            args.entry = args.exit = args.entry_user = args.exit_user = None
            args.strict_host_keys = False
            install(args)
        elif choice == '10':
            recovery_menu()
        elif choice == '12':
            update_lists.main([])

    while True:
        existing, _, unit, _ = panel_backends(json.loads(operator.read_text()))
        migration = existing and unit == PILOT_SPA
        print('\nCOLDWIRE\n1 Status\n2 List users and devices\n3 Add device and export profile\n'
              '4 Revoke device\n5 SSH to entry\n6 SSH to exit\n7 Revoke user and all their devices\n'
              '8 Import an AmneziaVPN profile' + ('\n9 Exit migration' if migration else '') +
              '\n10 Restore from backup\n11 Create backup\n12 Update split-tunneling lists\n0 Exit')
        try:
            choice = input('> ').strip()
        except EOFError:
            return
        try:
            if choice == '0':
                return
            if choice == '1':
                status(args)
            elif choice in ('2', '3', '4', '7'):
                args.action, args.name = {'2': 'list', '3': 'add', '4': 'revoke', '7': 'revoke-user'}[choice], None
                args.user = input('User name (Enter to use the device name): ').strip() if choice == '3' else None
                manage(args)
            elif choice in ('5', '6'):
                args.node = 'entry' if choice == '5' else 'exit'
                args.remote_command = []
                ssh(args)
            elif choice == '8':
                args.source = args.name = args.user = args.output = args.client_profile = None
                import_profile(args)
            elif choice == '9' and migration:
                migration_menu(args.folder)
            elif choice == '10':
                recovery_menu()
            elif choice == '11':
                path = input('Backup folder (Enter for the local backup folder): ').strip().strip('"')
                portable = os.name == 'nt' and input('Use a portable recovery key? [y/N] ').strip().lower() in ('y', 'yes')
                backup_action(argparse.Namespace(folder=args.folder, to=Path(path) if path else None,
                                                  portable_key=portable))
            elif choice == '12':
                update_lists.main([])
        except (EOFError, KeyboardInterrupt):
            return
        except (*PANEL_ERRORS, *RECOVERY_ERRORS) as error:
            print(f'COLDWIRE: {error}', file=sys.stderr)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    default = ROOT / 'private/coldwire-installation'
    installed = restore_backup.data_home() / 'access-panel'
    if not (default / 'operator.json').is_file() and (installed / 'operator.json').is_file():
        default = installed
    parser.add_argument('--folder', type=Path, default=default)
    parser.add_argument('--allow-private-endpoint', action='store_true', help='Allow local VM/LAN addresses for setup')
    commands = parser.add_subparsers(dest='command')
    setup = commands.add_parser('install')
    setup.add_argument('--allow-private-endpoint', action='store_true', default=argparse.SUPPRESS)
    setup.add_argument('--strict-host-keys', action='store_true')
    for role in ('entry', 'exit'):
        setup.add_argument('--' + role)
        setup.add_argument('--' + role + '-user')
    users = commands.add_parser('manage')
    users.add_argument('action', nargs='?', choices=('add', 'revoke', 'revoke-user', 'list'))
    users.add_argument('name', nargs='?')
    users.add_argument('--user')
    login = commands.add_parser('ssh')
    login.add_argument('node', choices=('entry', 'exit'))
    login.add_argument('remote_command', nargs=argparse.REMAINDER)
    commands.add_parser('status')
    migration = commands.add_parser('import-profile', help='Enroll an existing AmneziaWG peer and export its COLDWIRE profile')
    migration.add_argument('source', type=Path)
    migration.add_argument('name')
    migration.add_argument('--client-profile', type=Path)
    migration.add_argument('--output', type=Path)
    migration.add_argument('--user')
    cutover = commands.add_parser('migrate-exit', help='Move B from Docker to systemd')
    cutover.add_argument('action', choices=('stage', 'status', 'confirm', 'rollback'))
    cutover.add_argument('--timeout', type=int, default=600, help='Rollback timeout in seconds (stage only)')
    restore_backup.parser_options(commands.add_parser('restore', help='Check a backup or recover an installation'))
    backup = commands.add_parser('backup', help='Back up A, B and the operator folder')
    backup.add_argument('--to', type=Path, help='Destination folder for the encrypted archive')
    backup.add_argument('--portable-key', action='store_true', help='Protect the recovery key with a passphrase instead of Windows DPAPI')
    update_lists.parser_options(commands.add_parser('update-lists', help='Generate the two AmneziaVPN split-tunneling lists'))
    args = parser.parse_args()
    try:
        return {None: panel, 'install': install, 'manage': manage, 'ssh': ssh, 'status': status,
                'import-profile': import_profile, 'migrate-exit': migrate_exit,
                'restore': restore_action, 'backup': backup_action, 'update-lists': update_lists.generate}[args.command](args)
    except (*PANEL_ERRORS, *RECOVERY_ERRORS, subprocess.CalledProcessError) as error:
        parser.exit(1, f'COLDWIRE: {type(error).__name__}: {error}\n')


if __name__ == '__main__':
    sys.exit(main())
