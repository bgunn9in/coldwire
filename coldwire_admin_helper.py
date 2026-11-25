"""COLDWIRE desktop client bridge. One private JSON request on stdin."""

from argparse import ArgumentParser, Namespace
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import re
import secrets
import socket
import sys
from tempfile import TemporaryDirectory

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import paramiko

import coldwire_access as panel
import create_backup
from deploy import fingerprint, validate_address
from exit_config import replace_private, write_private
import restore_backup


MAGIC = b'COLDWIRE-OPERATOR-1\0'
PORTABLE = b'COLDWIRE-PORTABLE-OPERATOR-1\0'
REQUEST_LIMIT = 1 << 20
DEVICE_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,47}')
OPERATIONS = {'list', 'add', 'pause', 'resume', 'revoke', 'pause-user', 'resume-user', 'revoke-user'}


def inspect_endpoints(request, allow_private):
    result = []
    for role in ('entry', 'exit'):
        endpoint = request[role]
        host, _, port = endpoint.partition(':')
        host = validate_address(host, allow_private)
        port = int(port or '22')
        if not 1 <= port <= 65535:
            raise ValueError('Invalid port')
        with socket.create_connection((host, port), timeout=10) as connection:
            transport = paramiko.Transport(connection)
            try:
                transport.start_client(timeout=10)
                key = transport.get_remote_server_key()
                if key.get_name() != 'ssh-ed25519':
                    raise ValueError('Expected a server Ed25519 host key')
                result.append(fingerprint(key))
            finally:
                transport.close()
    return {'fingerprints': result}


def seal_operator(folder, path, key):
    payload = create_backup.operator_archive(folder, create_backup.operator_files(folder))
    nonce = secrets.token_bytes(12)
    replace_private(path, MAGIC + nonce + AESGCM(key).encrypt(nonce, payload, MAGIC))


def unseal_operator(path, folder, key):
    with path.open('rb') as stream:
        raw = stream.read(restore_backup.LIMIT + 1)
    if len(raw) > restore_backup.LIMIT or not raw.startswith(MAGIC) or len(raw) < len(MAGIC) + 28:
        raise ValueError('Invalid operator file')
    offset = len(MAGIC)
    payload = restore_backup.decrypt(key, raw[offset:offset + 12], raw[offset + 12:], MAGIC)
    restore_backup.restore_operator(payload, folder)


def handle_operation(request, folder, allow_private, checkpoint):
    action = request['action']
    if action == 'attach':
        if folder.exists():
            raise ValueError('An operator is already configured')
        existing = Path(request['operatorFolder']).resolve()
        if not (existing / 'operator.json').is_file():
            raise ValueError('Choose the existing COLDWIRE operator folder')
        archive = create_backup.operator_archive(existing, create_backup.operator_files(existing))
        restore_backup.restore_operator(archive, folder)
        panel.status(Namespace(folder=folder))
        return {'installed': True}
    if action == 'restore-operator':
        if folder.exists():
            raise ValueError('An operator is already configured')
        with Path(request['source']).open('rb') as stream:
            raw = stream.read(restore_backup.LIMIT + 1)
        if not raw.startswith(PORTABLE) or not len(PORTABLE) + 44 <= len(raw) <= restore_backup.LIMIT:
            raise ValueError('Not a COLDWIRE operator backup')
        offset = len(PORTABLE)
        salt = raw[offset:offset + 16]
        key = restore_backup.password_key(request['passphrase'], salt)
        payload = restore_backup.decrypt(key, raw[offset + 16:offset + 28], raw[offset + 28:], PORTABLE + salt)
        restore_backup.restore_operator(payload, folder)
        panel.status(Namespace(folder=folder))
        return {'installed': True}
    if action == 'install':
        if folder.exists():
            raise ValueError('An operator is already configured')
        settings = {}
        for role in ('entry', 'exit'):
            settings[role] = request[role]
            settings[role + '_user'] = request[role + 'User']
            settings[role + '_password'] = request.get(role + 'Password', '')
            settings[role + '_key_path'] = request.get(role + 'Key')
            settings[role + '_key_passphrase'] = request.get(role + 'KeyPassphrase', '')
            pin = request[role + 'Fingerprint']
            if not re.fullmatch(r'SHA256:[A-Za-z0-9+/]{43}', pin):
                raise ValueError('Confirm both SSH fingerprints before installation')
            settings[role + '_fingerprint'] = pin
        panel.install(Namespace(folder=folder, allow_private_endpoint=allow_private, strict_host_keys=True,
                                unattended_owner=True, routing=request.get('routing', 'ru-services'), **settings))
        return {'installed': True}
    if action == 'state':
        return {'installed': (folder / 'operator.json').is_file()}
    if not (folder / 'operator.json').is_file():
        raise ValueError('Install or attach COLDWIRE first')
    if action == 'backup-operator':
        password = request['passphrase']
        output = Path(request['output'])
        if len(password) < 12 or output.suffix.lower() != '.cwoperator' or not output.is_absolute():
            raise ValueError('Choose a .cwoperator file and a passphrase with at least 12 characters')
        payload = create_backup.operator_archive(folder, create_backup.operator_files(folder))
        salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
        key = restore_backup.password_key(password, salt)
        write_private(output, PORTABLE + salt + nonce + AESGCM(key).encrypt(nonce, payload, PORTABLE + salt))
        return {}
    if action == 'export':
        device = request['device']
        if not DEVICE_ID.fullmatch(device):
            raise ValueError('Unknown device')
        record = panel.load_devices(folder / 'devices.json').get(device)
        if not record or any(record.get(state) for state in ('paused', 'user_paused', 'pending')):
            raise ValueError('The device is unknown or its access is suspended')
        existing = folder / (device + '.vpn')
        output = Path(request['output'])
        if output.suffix.lower() != '.vpn' or not output.is_absolute():
            raise ValueError('Choose a destination .vpn file')
        write_private(output, existing.read_bytes())
        return {}
    if action not in OPERATIONS:
        raise ValueError('Unknown operator action')
    response = StringIO()
    with redirect_stdout(response):
        panel.manage(Namespace(folder=folder, action=action, name=request.get('device', ''),
                               user=request.get('user'), routing=request.get('routing'), json=True, checkpoint=checkpoint))
    if action == 'list':
        return {'devices': json.loads(response.getvalue())}
    return {}


def execute(request, state_path, allow_private):
    if request['action'] == 'preflight':
        return inspect_endpoints(request, allow_private)
    key = bytes.fromhex(request['stateKey'])
    if len(key) != 32:
        raise ValueError('Invalid operator key')
    state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with panel.operator_lock(state_path.with_suffix('.lock')), TemporaryDirectory(dir=state_path.parent, prefix='.operator-') as runtime:
        folder = Path(runtime) / 'operator'
        if state_path.exists():
            unseal_operator(state_path, folder, key)
        action = request['action']

        def checkpoint():
            seal_operator(folder, state_path, key)

        if action in ('attach', 'restore-operator'):
            value = handle_operation(request, folder, allow_private, checkpoint)
            checkpoint()
            return value
        try:
            return handle_operation(request, folder, allow_private, checkpoint)
        finally:
            if action not in ('list', 'state', 'export', 'backup-operator') and (folder / 'operator.json').is_file():
                checkpoint()


def invoke(raw, state_path, allow_private=False):
    try:
        if len(raw) > REQUEST_LIMIT:
            raise ValueError('Request too large')
        request = json.loads(raw)
        with redirect_stdout(StringIO()):
            response = execute(request, Path(state_path), allow_private)
        return json.dumps({'ok': True, **response}, ensure_ascii=True)
    except Exception as error:
        return json.dumps({'ok': False, 'error': type(error).__name__})


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--allow-private-endpoint', action='store_true')
    args = parser.parse_args()
    response = invoke(sys.stdin.buffer.read(REQUEST_LIMIT + 1), args.state, args.allow_private_endpoint)
    print(response)
    return 0 if json.loads(response)['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
