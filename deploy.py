#!/usr/bin/env python3
"""Deploy two NEW Ubuntu 22.04 servers over SSH; other OS versions are untested."""
import argparse
import base64
from dataclasses import dataclass, field
import getpass
import hashlib
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import socket
import sys
import tarfile
import time

from convert_profile import decode, awg_section, client_config
from exit_config import write_private

ROOT = Path(__file__).resolve().parent
REMOTE = '/opt/awg-relay-kit'
ENTRY_FILES = ('servers/install-entry.sh', 'servers/confirm-entry.sh', 'servers/rollback-entry.sh', 'servers/preflight-host.sh')
EXIT_FILES = ('install_exit.py', 'exit_config.py', 'convert_profile.py', 'servers/native-runtime.py',
              'servers/probe-relay.py', 'servers/install-exit.sh', 'servers/backup-exit.sh',
              'servers/restore-exit.sh', 'dist/awg-native-linux-amd64.tar.gz', 'dist/awg-native-linux-amd64.sha256')
XRAY_FILES = ('install_xray.py', 'xray_config.py', 'convert_xray.py', 'servers/install-xray.sh', 'servers/probe-xray.py',
              'dist/xray-native-linux-amd64.tar.gz', 'dist/xray-native-linux-amd64.sha256')


class DeployError(RuntimeError):
    pass


@dataclass
class Server:
    role: str
    address: str
    host: str
    port: int
    username: str
    password: str = field(repr=False)
    sudo_password: str = field(repr=False)
    fingerprint: str = ''


def fingerprint(key):
    return 'SHA256:' + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip('=')


def verify_host_key(path, server, key, accept_new):
    import paramiko
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    known = paramiko.HostKeys()
    if path.exists():
        known.load(str(path))
    name = server.host if server.port == 22 else f'[{server.host}]:{server.port}'
    saved = known.lookup(name)
    actual = fingerprint(key)
    if server.fingerprint and server.fingerprint != actual:
        raise DeployError(server.role + ': SSH fingerprint mismatch; no password was sent')
    if saved:
        if key.get_name() not in saved or saved[key.get_name()].asbytes() != key.asbytes():
            raise DeployError(server.role + ': known SSH host key changed; no password was sent')
    else:
        if not server.fingerprint and not accept_new:
            raise DeployError(server.role + ': unknown host key ' + actual + '; specify its fingerprint or --accept-new-host-keys')
        known.add(name, key.get_name(), key)
        if not path.exists():
            write_private(path, b'')
        known.save(str(path))
        path.chmod(0o600)
    return actual


class Remote:
    def __init__(self, server, known_hosts, accept_new):
        self.server, self.transport, self.sftp = server, None, None
        self.root, self.needs_sudo_password = False, False
        self.stage, self.kit = None, None
        import paramiko
        try:
            connection = socket.create_connection((server.host, server.port), timeout=15)
            self.transport = paramiko.Transport(connection)
            self.transport.banner_timeout = 15
            self.transport.auth_timeout = 20
            self.transport.start_client(timeout=15)
            self.host_fingerprint = verify_host_key(known_hosts, server, self.transport.get_remote_server_key(), accept_new)
            # Identity is checked before any authentication secret is transmitted.
            self.transport.auth_password(server.username, server.password)
            self.transport.set_keepalive(20)
            self.root = self.run('id -u', privileged=False).strip() == b'0'
            if not self.root:
                self.needs_sudo_password = self.run('sudo -n true', privileged=False, check=False)[0] != 0
                self.run('test "$(id -u)" = 0')
            self.sftp = paramiko.SFTPClient.from_transport(self.transport)
        except BaseException:
            self.close()
            raise

    def run(self, script, *, privileged=True, check=True, timeout=900):
        # sudo alone consumes its password; child programs never inherit that input.
        command = 'bash -e -o pipefail -c ' + shlex.quote('exec </dev/null\n' + script)
        payload = b''
        if privileged and not self.root:
            if self.needs_sudo_password:
                command = "sudo -S -p '' -- " + command
                payload = (self.server.sudo_password + '\n').encode()
            else:
                command = 'sudo -n -- ' + command
        channel = self.transport.open_session(timeout=15)
        output, errors = bytearray(), bytearray()
        try:
            channel.exec_command(command)
            if payload:
                channel.sendall(payload)
            channel.shutdown_write()
            deadline = time.monotonic() + timeout
            while True:
                while channel.recv_ready():
                    output.extend(channel.recv(65536))
                while channel.recv_stderr_ready():
                    errors.extend(channel.recv_stderr(65536))
                if len(output) + len(errors) > 16_000_000:
                    raise DeployError(self.server.role + ': remote output exceeded limit')
                if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
                    break
                if time.monotonic() > deadline:
                    raise DeployError(self.server.role + ': remote command timed out')
                time.sleep(0.02)
            code = channel.recv_exit_status()
        finally:
            channel.close()
        if not check:
            return code, bytes(output)
        if code:
            tag = re.search(rb'^KIT_ERROR=([A-Z_]{1,80})$', bytes(errors), re.MULTILINE)
            phase = '; phase ' + tag[1].decode('ascii') if tag else ''
            raise DeployError(f'{self.server.role}: remote command failed (exit {code}{phase}); private output suppressed')
        return bytes(output)

    def upload(self, payload):
        self.stage = self.run('mktemp -d /tmp/awg-relay-deploy-XXXXXXXX', privileged=False).decode().strip()
        if not re.fullmatch(r'/tmp/awg-relay-deploy-[A-Za-z0-9]+', self.stage):
            raise DeployError('Unexpected remote staging path')
        path = self.stage + '/payload.tar.gz'
        with self.sftp.open(path, 'wb') as stream:
            stream.write(payload)
        self.sftp.chmod(path, 0o600)
        self.kit = self.stage + '/kit'
        self.run('mkdir -m 700 ' + shlex.quote(self.kit) + '; tar -xzf ' + shlex.quote(path) + ' -C ' + shlex.quote(self.kit), privileged=False)

    def promote(self):
        self.run('test ! -e ' + REMOTE + '; mv -T --no-clobber ' + shlex.quote(self.kit) + ' ' + REMOTE +
                 '; test ! -e ' + shlex.quote(self.kit) + '; chown -R root:root ' + REMOTE)
        self.kit = REMOTE

    def close(self):
        if self.sftp:
            self.sftp.close()
        if self.transport:
            self.transport.close()


def package(names):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as archive:
        for name in names:
            path = ROOT / name
            if path.is_symlink():
                raise ValueError('Symlink in deployment source')
            content = path.read_bytes()
            if path.suffix in {'.py', '.sh'}:
                content = content.replace(b'\r\n', b'\n')
            member = tarfile.TarInfo(name)
            member.size, member.mode = len(content), 0o600
            archive.addfile(member, io.BytesIO(content))
    return output.getvalue()


def validate_address(value, private=False):
    address = ipaddress.IPv4Address(value)
    lan = private and any(address in ipaddress.IPv4Network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
    if (not address.is_global or address.is_multicast) and not lan:
        raise ValueError('Use public server IPv4 addresses; private LAN needs --allow-private-endpoint')
    return str(address)


def server_from_args(args, role):
    address = getattr(args, role) or input(f'{role} server IPv4: ').strip()
    address = validate_address(address, args.allow_private_endpoint)
    host = getattr(args, role + '_ssh_host') or address
    port = getattr(args, role + '_ssh_port')
    if port is None:
        port = int(input(f'{role} SSH port [22]: ').strip() or '22') if sys.stdin.isatty() and not args.non_interactive else 22
        setattr(args, role + '_ssh_port', port)
    username = getattr(args, role + '_user') or input(f'{role} SSH login [root]: ').strip() or 'root'
    variable = getattr(args, role + '_password_env')
    password = os.environ.get(variable)
    if password is None:
        if args.non_interactive or not sys.stdin.isatty():
            raise ValueError('Set the password environment variable: ' + variable)
        password = getpass.getpass(f'{role} SSH password (hidden): ')
    sudo_password = os.environ.get('AWG_' + role.upper() + '_SUDO_PASSWORD', password)
    if not password or any(c in password + sudo_password for c in '\r\n\x00'):
        raise ValueError('Password must be nonempty and contain no newline/NUL')
    return Server(role, address, host, port, username, password, sudo_password,
                  getattr(args, role + '_fingerprint') or '')


def retrieve_profiles(remote, args, output, protocol=None):
    protocol = protocol or args.protocol
    names = ('client.conf', 'client.vpn', 'client-via-entry.conf', 'client-via-entry.vpn') if protocol in ('awg', 'both') else ()
    if protocol in ('reality', 'both'):
        names += ('xray-client.json', 'xray-client.txt', 'xray-client-via-entry.json', 'xray-client-via-entry.txt')
    for name in names:
        xray = name.startswith('xray-')
        base = '/root/awg-relay-kit-xray-clients/' if xray else '/root/awg-relay-kit-clients/'
        raw = remote.run('cat -- ' + shlex.quote(base + args.client + '/' + name))
        if name.endswith('.vpn'):
            config = client_config(awg_section(decode(raw)))
            expected = args.entry_server.address if 'via-entry' in name else args.exit_server.address
            expected_port = args.entry_port if 'via-entry' in name else args.exit_port
            if config['hostName'] != expected or config['port'] != expected_port:
                raise DeployError('Downloaded profile endpoint did not match deployment')
        if xray and name.endswith('.json'):
            outbound = json.loads(raw)['outbounds'][0]
            args.reality_server_name = outbound['streamSettings']['realitySettings']['serverName']
            config = outbound['settings']['vnext'][0]
            expected = args.entry_server.address if 'via-entry' in name else args.exit_server.address
            port = args.reality_entry_port if 'via-entry' in name else args.reality_exit_port
            if config['address'] != expected or config['port'] != port:
                raise DeployError('Downloaded Xray endpoint did not match deployment')
        write_private(output / name, raw)
    for name in ('ru-direct.amnezia.json', 'ru-services.amnezia.json'):
        if not (output / name).exists():
            write_private(output / name, (ROOT / name).read_bytes())


def deploy(args, connect=Remote):
    args.protocol = getattr(args, 'protocol', None) or 'awg'
    if args.protocol not in ('awg', 'reality', 'both'):
        raise ValueError('Choose awg, reality or both')
    use_awg, use_xray = args.protocol in ('awg', 'both'), args.protocol in ('reality', 'both')
    if any(p is not None and not 1 <= p <= 65535 for p in (getattr(args, 'reality_entry_port', None), getattr(args, 'reality_exit_port', None))):
        raise ValueError('Invalid REALITY TCP port')
    args.entry_server = server_from_args(args, 'entry')
    args.exit_server = server_from_args(args, 'exit')
    if args.entry_server.address == args.exit_server.address:
        raise ValueError('Entry and exit must be different servers')
    if not all(1 <= p <= 65535 for p in (args.entry_port, args.exit_port, args.entry_ssh_port, args.exit_ssh_port)):
        raise ValueError('Port must be between 1 and 65535')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,47}', args.client):
        raise ValueError('Invalid client name')
    if args.output.exists():
        raise FileExistsError('Use a new output directory; existing profiles are never overwritten')
    entry, exit_server = None, None
    step, confirmed = 'SSH connection/identity', False
    try:
        print('Connecting to both servers; verifying SSH identity and sudo access')
        entry = connect(args.entry_server, args.known_hosts, args.accept_new_host_keys)
        exit_server = connect(args.exit_server, args.known_hosts, args.accept_new_host_keys)
        if entry.run('cat /etc/machine-id').strip() == exit_server.run('cat /etc/machine-id').strip():
            raise DeployError('Both SSH connections reach the same machine; installation refused')
        step = 'upload and read-only preflight'
        print('Uploading the public toolkit; checking that BOTH servers are clean')
        entry.upload(package(ENTRY_FILES))
        payload = tuple(n for n in EXIT_FILES if use_awg or not n.startswith('dist/awg-'))
        payload += ('servers/preflight-host.sh',) + (XRAY_FILES if use_xray else ())
        exit_server.upload(package(payload))
        # Inspect BOTH machines before installing even bootstrap dependencies.
        for remote in (entry, exit_server):
            remote.run(f'bash {remote.kit}/servers/preflight-host.sh --check')
        for remote in (entry, exit_server):
            remote.run(f'bash {remote.kit}/servers/preflight-host.sh --bootstrap')
        if use_xray:
            for role, remote in (('entry', entry), ('exit', exit_server)):
                requested = getattr(args, 'reality_' + role + '_port', None)
                port = requested or 443
                if remote.run(f'ss -H -ltn "sport = :{port}"'):
                    server = getattr(args, role + '_server')
                    if requested is None and server.host == server.address and server.port == 443 and not remote.run('ss -H -ltn "sport = :8443"'):
                        port = 8443
                    else:
                        raise DeployError(role + ': REALITY TCP port occupied; SSH will not be changed')
                if not 1 <= port <= 65535:
                    raise ValueError('Invalid REALITY TCP port')
                setattr(args, 'reality_' + role + '_port', port)
                print(role + ' REALITY TCP port:', port)
        environment = 'env LC_ALL=C AWG_ALLOW_PRIVATE_ENDPOINT=' + ('1' if args.allow_private_endpoint else '0')
        def entry_command(root):
            udp = str(args.entry_port) if use_awg else '-'
            tcp = args.reality_entry_port if use_xray else 0
            backend = args.reality_exit_port if use_xray else 443
            return f'{environment} bash {root}/servers/install-entry.sh {args.entry_server.address} {args.exit_server.address} {udp} {args.exit_port} {tcp} {backend}'
        def exit_command(root):
            command = f'python3 {root}/install_exit.py install --endpoint {args.exit_server.address} --entry {args.entry_server.address} --port {args.exit_port} --entry-port {args.entry_port} --client {args.client}'
            return command + (' --allow-private-endpoint' if args.allow_private_endpoint else '')
        def xray_command(root):
            command = f'python3 {root}/install_xray.py install --endpoint {args.exit_server.address} --entry {args.entry_server.address} --port {args.reality_exit_port} --entry-port {args.reality_entry_port} --client {args.client}'
            if use_awg:
                command += ' --with-awg'
            if args.allow_private_endpoint:
                command += ' --allow-private-endpoint'
            if getattr(args, 'reality_target', None):
                command += ' --target ' + shlex.quote(args.reality_target)
            return command
        entry.run('env AWG_PREFLIGHT_ONLY=1 ' + entry_command(entry.kit))
        if use_awg:
            exit_server.run(exit_command(exit_server.kit) + ' --check-only')
        if use_xray:
            exit_server.run(xray_command(exit_server.kit) + ' --check-only')
        entry.promote()
        exit_server.promote()
        step = 'exit installation'
        print('Installing selected native protocol(s) on the exit:', args.protocol)
        if use_awg:
            exit_server.run(exit_command(REMOTE))
            args.output.mkdir(parents=True, mode=0o700)
            retrieve_profiles(exit_server, args, args.output, protocol='awg')
        if use_xray:
            exit_server.run(xray_command(REMOTE))
            if not use_awg:
                args.output.mkdir(parents=True, mode=0o700)
            retrieve_profiles(exit_server, args, args.output, protocol='reality')
        step = 'entry installation and authenticated relay probe'
        print('Direct profile saved. Installing the entry with its 5-minute rollback timer')
        entry.run(entry_command(REMOTE))
        if use_awg:
            proof = json.loads(exit_server.run(f'python3 {REMOTE}/servers/probe-relay.py --entry {args.entry_server.address} --port {args.entry_port}').decode())
            if not all(proof.get(k) is True for k in ('handshake', 'server_sees_entry', 'temporary_peer_removed')):
                raise DeployError('AWG relay verification did not pass')
        if use_xray:
            proof = json.loads(exit_server.run(f'python3 {REMOTE}/servers/probe-xray.py --entry {args.entry_server.address} --port {args.reality_entry_port} --client {args.client}').decode())
            if not all(proof.get(k) is True for k in ('application_data', 'server_sees_entry', 'temporary_process_removed')):
                raise DeployError('REALITY relay verification did not pass')
        step = 'entry confirmation'
        entry.run('bash /var/lib/awg-relay-kit/confirm-entry.sh')
        confirmed = True
        report = f'''# Deployment complete

Selected protocol(s): {args.protocol}
Entry IPv4: {args.entry_server.address}
Exit IPv4: {args.exit_server.address}
AWG entry/exit UDP ports (if selected): {args.entry_port}/{args.exit_port}
REALITY entry/exit TCP ports (if selected): {getattr(args, 'reality_entry_port', None)}/{getattr(args, 'reality_exit_port', None)}
REALITY SNI (if selected): {getattr(args, 'reality_server_name', None)}
Entry SSH: {args.entry_server.username}@{args.entry_server.host}:{args.entry_server.port}
Exit SSH: {args.exit_server.username}@{args.exit_server.host}:{args.exit_server.port}
Entry SSH fingerprint: {entry.host_fingerprint}
Exit SSH fingerprint: {exit_server.host_fingerprint}

Native systemd services; no Docker or Go compiler installed on the VPS.
ALL selected protocol probes via entry passed before the rollback was cancelled.
Toolkit retained on each server at {REMOTE} for administration.
If AWG selected: import client-via-entry.vpn; client.vpn is the direct fallback.
If REALITY selected: import xray-client-via-entry.json; .txt contains a vless URI.
Direct and via-entry files of each protocol are alternatives for ONE client.
Choose ONE of the two RU JSON snapshots and replace the client's bypass list.
SSH passwords are not stored in this folder or in VPN exports.
'''
        write_private(args.output / 'deployment.md', report)
        print('Deployment complete. Private client files:', args.output)
    except BaseException:
        print('Deployment stopped during ' + step + '. Private remote output was suppressed.', file=sys.stderr)
        if confirmed:
            print('The entry was already confirmed; installed services and downloaded profiles are retained.', file=sys.stderr)
        else:
            print('If entry was armed and not confirmed, its independent rollback timer applies. Any installed exit/direct profile is retained.', file=sys.stderr)
        raise
    finally:
        for remote in (entry, exit_server):
            if remote:
                if remote.stage:
                    try:
                        remote.run('rm -rf -- ' + shlex.quote(remote.stage))
                    except Exception:
                        pass
                remote.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for role in ('entry', 'exit'):
        parser.add_argument('--' + role, help='Server IPv4; prompted when omitted')
        parser.add_argument('--' + role + '-user', help='SSH username; prompted when omitted')
        parser.add_argument('--' + role + '-ssh-host', help='Optional separate SSH hostname/address (NAT/lab)')
        parser.add_argument('--' + role + '-ssh-port', type=int, help='SSH port; wizard default 22')
        parser.add_argument('--' + role + '-password-env', default='AWG_' + role.upper() + '_PASSWORD')
        parser.add_argument('--' + role + '-fingerprint', help='Expected SHA256: SSH host-key fingerprint')
    parser.add_argument('--entry-port', type=int, default=32497)
    parser.add_argument('--exit-port', type=int, default=32497)
    parser.add_argument('--protocol', choices=('awg', 'reality', 'both'), help='Wizard selection; non-interactive default awg')
    parser.add_argument('--reality-entry-port', type=int)
    parser.add_argument('--reality-exit-port', type=int)
    parser.add_argument('--reality-target', help='Optional TLS1.3/h2 target HOST[:PORT]; otherwise selected automatically')
    parser.add_argument('--client', default='client1')
    parser.add_argument('--output', type=Path, help='New private output directory; otherwise an automatic unique directory')
    parser.add_argument('--known-hosts', type=Path, default=ROOT / 'private/known_hosts')
    parser.add_argument('--accept-new-host-keys', action='store_true', help='Trust/save first-seen keys; changed keys still fail BEFORE password authentication')
    parser.add_argument('--strict-host-keys', action='store_true', help='Disable wizard first-contact TOFU; require known key or fingerprint')
    parser.add_argument('--non-interactive', action='store_true')
    parser.add_argument('--allow-private-endpoint', action='store_true', help='Explicit local RFC1918 lab support')
    args = parser.parse_args()
    if not args.non_interactive and sys.stdin.isatty():
        if args.protocol is None:
            choice = input('Protocol: 1=AmneziaWG 3.1, 2=REALITY, 3=both [1]: ').strip() or '1'
            args.protocol = {'1': 'awg', '2': 'reality', '3': 'both'}.get(choice)
            if args.protocol is None:
                parser.error('Choose 1, 2 or 3')
        if not args.strict_host_keys:
            args.accept_new_host_keys = True
            print('First-contact SSH trust (TOFU): new keys are saved; changed keys are always rejected.')
    if args.strict_host_keys and args.accept_new_host_keys:
        parser.error('Choose strict host keys OR first-contact trust')
    if args.output is None:
        args.output = ROOT / 'private' / ('deployment-' + time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + os.urandom(3).hex())
    if args.non_interactive and not all((args.entry, args.exit, args.entry_user, args.exit_user)):
        parser.error('--non-interactive needs both addresses and usernames')
    try:
        import paramiko
    except ImportError:
        print('Install operator-PC dependencies: python -m pip install -r requirements-deploy.txt', file=sys.stderr)
        return 1
    try:
        os.umask(0o077)
        deploy(args)
    except DeployError as error:
        print(str(error) + '. See docs/deploy.md.', file=sys.stderr)
        return 1
    except (OSError, ValueError, paramiko.SSHException):
        print('Setup failed; credentials and private output were not printed. See docs/deploy.md.', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('Setup interrupted. The entry safety timer, if armed, remains active.', file=sys.stderr)
        return 130
    return 0


if __name__ == '__main__':
    sys.exit(main())
