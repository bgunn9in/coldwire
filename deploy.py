#!/usr/bin/env python3
"""SSH transport and native AmneziaWG installation for the access panel."""
import base64
from dataclasses import dataclass, field
import hashlib
import io
import ipaddress
import json
from pathlib import Path
import re
import shlex
import socket
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
    key_path: Path | None = None
    key_passphrase: bytes | None = field(default=None, repr=False)


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
    def __init__(self, server, known_hosts, accept_new, *, connection=None, check_sudo=True):
        self.server, self.transport, self.sftp = server, None, None
        self.root, self.needs_sudo_password = False, False
        self.stage, self.kit = None, None
        import paramiko
        try:
            if connection is None:
                connection = socket.create_connection((server.host, server.port), timeout=15)
            self.transport = paramiko.Transport(connection)
            self.transport.banner_timeout = 15
            self.transport.auth_timeout = 20
            self.transport.start_client(timeout=15)
            self.host_fingerprint = verify_host_key(known_hosts, server, self.transport.get_remote_server_key(), accept_new)
            # Identity is checked before any authentication secret is transmitted.
            if server.key_path:
                try:
                    if server.key_passphrase is None:
                        key = paramiko.PKey.from_path(server.key_path)
                    else:
                        key = paramiko.PKey.from_path(server.key_path, password=server.key_passphrase)
                except (OSError, TypeError, ValueError, paramiko.UnknownKeyType) as error:
                    raise DeployError(server.role + ': cannot read SSH private key') from error
                self.transport.auth_publickey(server.username, key)
            else:
                self.transport.auth_password(server.username, server.password)
            self.transport.set_keepalive(20)
            self.root = self.run('id -u', privileged=False).strip() == b'0'
            if not self.root:
                self.needs_sudo_password = self.run('sudo -n true', privileged=False, check=False)[0] != 0
                if check_sudo and self.needs_sudo_password and not server.sudo_password:
                    raise DeployError(f'{server.role}: set AWG_{server.role.upper()}_SUDO_PASSWORD for this account')
                if check_sudo:
                    self.run('test "$(id -u)" = 0')
            self.sftp = paramiko.SFTPClient.from_transport(self.transport)
        except BaseException:
            self.close()
            raise

    def run(self, script, *, privileged=True, check=True, timeout=900, output_limit=16_000_000):
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
                    if len(output) > output_limit:
                        raise DeployError(self.server.role + ': remote output exceeded limit')
                while channel.recv_stderr_ready():
                    errors.extend(channel.recv_stderr(65536))
                    if len(output) + len(errors) > output_limit:
                        raise DeployError(self.server.role + ': remote output exceeded limit')
                if (channel.closed or channel.eof_received) and channel.exit_status_ready() and not (
                    channel.recv_ready() or channel.recv_stderr_ready()
                ):
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


def probe_relay(exit_server, address, port):
    address = ipaddress.IPv4Address(address)
    proof = json.loads(exit_server.run(
        f'python3 {REMOTE}/servers/probe-relay.py --entry {address} --port {port}', timeout=65))
    if not all(proof.get(name) is True for name in ('handshake', 'server_sees_entry', 'temporary_peer_removed')):
        raise DeployError('AWG relay verification did not pass')


def deploy(entry, exit_server, output, port, allow_private=False):
    if output.exists():
        raise FileExistsError('Use a new output directory; existing profiles are never overwritten')
    source, destination = entry.server.address, exit_server.server.address
    environment = 'env LC_ALL=C AWG_ALLOW_PRIVATE_ENDPOINT=' + ('1' if allow_private else '0')
    private_option = ' --allow-private-endpoint' if allow_private else ''
    nodes = (entry, exit_server)
    try:
        entry.upload(package(ENTRY_FILES))
        exit_server.upload(package(EXIT_FILES + ('servers/preflight-host.sh',)))
        for remote in nodes:
            remote.run(f'bash {remote.kit}/servers/preflight-host.sh --check')
        for remote in nodes:
            remote.run(f'bash {remote.kit}/servers/preflight-host.sh --bootstrap')
        entry_args = f'{source} {destination} {port} {port}'
        exit_args = (f'install --endpoint {destination} --entry {source} --port {port} '
                     f'--entry-port {port} --client client1{private_option}')
        entry.run(f'env AWG_PREFLIGHT_ONLY=1 {environment} bash {entry.kit}/servers/install-entry.sh {entry_args}')
        exit_server.run(f'python3 {exit_server.kit}/install_exit.py {exit_args} --check-only')
        for remote in nodes:
            remote.promote()
        print('Installing native AmneziaWG on B', flush=True)
        exit_server.run(f'python3 {REMOTE}/install_exit.py {exit_args}')
        output.mkdir(mode=0o700)
        profile = exit_server.run('cat /root/awg-relay-kit-clients/client1/client.vpn')
        client = client_config(awg_section(decode(profile)))
        if (client['hostName'], client['port']) != (destination, port):
            raise DeployError('Downloaded profile endpoint did not match B')
        write_private(output / 'client.vpn', profile)
        print('Installing UDP relay on A and testing it before confirmation', flush=True)
        entry.run(f'{environment} bash {REMOTE}/servers/install-entry.sh {entry_args}')
        probe_relay(exit_server, source, port)
        entry.run('bash /var/lib/awg-relay-kit/confirm-entry.sh')
    finally:
        for remote in nodes:
            if remote.stage:
                try:
                    remote.run('rm -rf -- ' + shlex.quote(remote.stage))
                except Exception:
                    pass
                remote.stage = None
