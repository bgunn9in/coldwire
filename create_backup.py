"""Collect an authenticated COLDWIRE backup over read-only SSH."""

from datetime import datetime, timezone
import gzip
from hashlib import sha256
from io import BytesIO
from ipaddress import IPv4Address
import json
import os
import posixpath
from shlex import quote
import stat
import tarfile
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from deploy import DeployError, ENTRY_FILES, EXIT_FILES, ROOT
from exit_migration import NATIVE_EXIT
import restore_backup as recovery


REMOTE_LIMIT = 64 * 1024 * 1024
UNIT = 'etc/systemd/system/'
LOCK = 'etc/coldwire-lockdown/'
NATIVE = 'var/lib/coldwire-native-exit/'
PILOT = 'var/lib/coldwire-spa-pilot/'
STANDARD = 'etc/awg-relay-kit-exit/'
COMMON = ('etc/nftables.conf', 'etc/ssh/coldwire_authorized_keys',
          'etc/ssh/sshd_config', 'etc/ssh/sshd_config.d', LOCK[:-1], 'opt/coldwire-lockdown')
PATTERNS = '''
etc/ssh/ssh_host_*_key* etc/sysctl.d/*coldwire* etc/sysctl.d/*blackice* etc/sysctl.d/*awg*
etc/tmpfiles.d/*coldwire*
etc/systemd/system/{blackice-relay,coldwire-*,awg-relay-kit-exit,cw-native-boot-rollback,ssh,docker}.*
etc/systemd/system/*.wants/{blackice-relay,coldwire-*,awg-relay-kit-exit,cw-native-boot-rollback}.*
'''.strip().replace('\n', ' ')
COMMON_REQUIRED = (LOCK + 'active.nft', LOCK + 'sshd.conf',
                   'etc/ssh/coldwire_authorized_keys', 'etc/ssh/ssh_host_ed25519_key',
                   UNIT + 'coldwire-lockdown.service', UNIT + 'coldwire-lockdown-ssh.service')
PANEL_FILES = set(ENTRY_FILES + EXIT_FILES) | set('''
    COLDWIRE-Admin.cmd COLDWIRE-Admin.sh setup.sh setup.ps1 requirements-deploy.txt
    COLDWIRE-Lists.cmd COLDWIRE-Lists.sh update_lists.py
    LICENSE THIRD_PARTY_NOTICES.md README.md README.ru.md
    coldwire_access.py deploy.py create_backup.py restore_backup.py exit_migration.py legacy_profiles.py
    docs/access-panel.md docs/ru/access-panel.md docs/lists.md docs/ru/lists.md
    docs/sources.md docs/ru/sources.md
    data/ru-networks.txt data/protected-vpn-networks.txt data/service-roots.txt data/service-addresses.txt
    ru-direct.amnezia.json ru-services.amnezia.json
    assets/coldwire-header.svg assets/coldwire-header.ru.svg
    assets/coldwire-topology.svg assets/coldwire-topology.ru.svg
    servers/lockdown_rules.py servers/spa_access.py servers/stage-access.sh servers/stage-lockdown.sh
    servers/coldwire-access-firewall.service servers/coldwire-lockdown-ssh.service
    servers/coldwire-lockdown.service servers/coldwire-spa.service servers/migrate-native-exit.py
    servers/spa/main.go servers/spa/go.mod
'''.split())


def node_files(pilot, migrated):
    entry_paths = ('etc/blackice-relay.nft', 'var/lib/awg-relay-kit',
                   'etc/coldwire-access', 'opt/coldwire-access', PILOT[:-1], 'opt/awg-relay-kit')
    exit_paths = (STANDARD[:-1], 'usr/local/libexec/awg-relay-kit', 'root/awg-relay-kit-clients',
                  'opt/awg-relay-kit', NATIVE[:-1], 'var/lib/cw-native-boot-rollback')
    entry_required = (('etc/blackice-relay.nft', UNIT + 'blackice-relay.service') +
                      ((LOCK + 'pilot-keys.json', PILOT + 'endpoint.env', PILOT + 'coldwire-spa',
                        PILOT + 'confirmed', UNIT + 'coldwire-spa-pilot.service') if pilot else
                       ('etc/coldwire-access/active.nft', 'etc/coldwire-access/spa-keys.json',
                        'opt/coldwire-access/coldwire-spa', UNIT + 'coldwire-spa.service',
                        UNIT + 'coldwire-access-firewall.service')))
    exit_required = ((NATIVE + 'native.awg', NATIVE + 'state.json', NATIVE + 'driver.py',
                      NATIVE + 'bin/awg', NATIVE + 'bin/amneziawg-go') if migrated else
                     (STANDARD + 'server.json', STANDARD + 'awg0.conf', 'usr/local/libexec/awg-relay-kit/awg',
                      'usr/local/libexec/awg-relay-kit/amneziawg-go', 'opt/awg-relay-kit/install_exit.py'))
    return ((entry_paths, entry_required), (exit_paths, exit_required + (UNIT + 'awg-relay-kit-exit.service',)))


def guard(node, files):
    guarded = ('/etc/coldwire-lockdown/pending.nft', '/etc/coldwire-lockdown/pending.timer',
               '/' + NATIVE + 'armed', '/var/lib/cw-native-boot-rollback/armed')
    conditions = '\n'.join(f'test ! -e {path}' for path in guarded)
    return node.run(f'''
{conditions}
cat /proc/sys/kernel/random/boot_id
systemctl show -p MainPID -p ActiveEnterTimestampMonotonic coldwire-lockdown-ssh.service
sha256sum -- {' '.join(quote('/' + path) for path in files)}
''', timeout=30)


def inspect_node(payload, role, required):
    with gzip.GzipFile(fileobj=BytesIO(payload)) as plain:
        size = 0
        while chunk := plain.read(64 * 1024):
            size += len(chunk)
            if size > recovery.LIMIT:
                raise ValueError(f'{role}: expanded archive exceeds the supported size')
    with tarfile.open(fileobj=BytesIO(payload), mode='r:gz') as archive:
        members = archive.getmembers()
        paths = {item.name: item for item in members}
        for item in members:
            if not recovery.linux_member(item.name) or not (item.isfile() or item.isdir() or item.issym() or item.islnk()):
                raise ValueError(f'{role}: unsupported member in backup')
        for path in required:
            item = paths.get(path)
            if item and (item.islnk() or item.issym()):
                target = item.linkname
                if item.issym() and not target.startswith('/'):
                    target = posixpath.join(posixpath.dirname(path), target)
                item = paths.get(posixpath.normpath(target).lstrip('/'))
            if not item or not item.isfile() or not item.size:
                raise ValueError(f'{role}: missing or empty {path}')
        return len(members)


def capture(node, paths, required):
    payload = node.run(f'''
cd /
paths=()
for path in {' '.join(quote(path) for path in COMMON + paths)} {PATTERNS}; do
    if test -e "$path" || test -L "$path"; then paths+=("$path"); fi
done
tar --numeric-owner -czf - -- "${{paths[@]}}"
''', timeout=180, output_limit=REMOTE_LIMIT)
    return payload, inspect_node(payload, node.server.role, COMMON_REQUIRED + required)


def operator_files(folder):
    files = {}
    total = 0
    for path in sorted(folder.rglob('*')):
        details = path.lstat()
        if (stat.S_ISLNK(details.st_mode)
                or getattr(details, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
                or not (stat.S_ISREG(details.st_mode) or stat.S_ISDIR(details.st_mode))):
            raise ValueError('Operator folder contains a link or special file')
        if stat.S_ISREG(details.st_mode):
            total += details.st_size
            if total > REMOTE_LIMIT:
                raise ValueError('Operator folder exceeds the supported size')
        files[path.relative_to(folder).as_posix()] = (details.st_mode, details.st_mtime_ns, details.st_size)
    return files


def operator_archive(folder, files):
    output = BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as archive:
        for name in files:
            path = folder / name
            item = archive.gettarinfo(str(path), arcname=name)
            item.mode = 0o700 if item.isdir() else 0o600
            if item.isdir():
                archive.addfile(item)
            else:
                with path.open('rb') as content:
                    archive.addfile(item, content)
    return output.getvalue()


def panel_package():
    output = BytesIO()
    binary = 'dist/coldwire-spa-linux-amd64'
    names = PANEL_FILES | ({binary} if (ROOT / binary).is_file() else set())
    with ZipFile(output, 'w', compression=ZIP_DEFLATED) as package:
        for name in sorted(names):
            path = ROOT / name
            content = path.read_bytes()
            if path.suffix in ('.sh', '.py', '.service'):
                content = content.replace(b'\r\n', b'\n')
            package.writestr(name, content)
    return output.getvalue()


def collect(folder, authorize):
    before = operator_files(folder)
    if not {'admin.key', 'ssh', 'known_hosts', 'operator.json'} <= before.keys():
        raise ValueError('This folder does not contain a complete COLDWIRE installation')
    manifest = json.loads((folder / 'operator.json').read_text())
    native = manifest.get('native_exit')
    if (native is None and manifest.get('legacy_exit')) or native not in (None, NATIVE_EXIT):
        raise ValueError('Backup supports COLDWIRE native AmneziaWG on B')
    pilot = manifest.get('pilot_spa', manifest.get('legacy_exit', False))
    plans = node_files(pilot, native is not None)
    parts, network, counts = {}, {}, {}
    with authorize(manifest, folder) as nodes:
        guards = [(LOCK + 'active.nft',) + tuple(path for path in required
                   if path.endswith(('.nft', '.json', '.env', '.awg', '.conf')))
                  for _, required in plans]
        tokens = [guard(node, files) for node, files in zip(nodes, guards)]
        for node, other, (paths, required) in zip(nodes, reversed(nodes), plans):
            role = node.server.role
            address = str(IPv4Address(other.server.address))
            route = json.loads(node.run(f'ip -j -4 route get {address}', timeout=15))[0]
            network[role] = {'address': str(IPv4Address(node.server.address)), 'wan': route['dev']}
            parts[role + '.tar.gz'], counts[role + '.tar.gz'] = capture(node, paths, required)
        if any(guard(node, files) != token for node, files, token in zip(nodes, guards, tokens)):
            raise DeployError('Server state changed during capture. Retry after changes finish')
    parts['operator.tar.gz'] = operator_archive(folder, before)
    if operator_files(folder) != before:
        raise ValueError('Operator files changed during capture. Retry after changes finish')
    with tarfile.open(fileobj=BytesIO(parts['operator.tar.gz']), mode='r:gz') as archive:
        recovery.operator_members(archive)
    counts['operator.tar.gz'] = len(before)
    parts['COLDWIRE-Access-Panel.zip'] = panel_package()
    return parts, network, counts


def encrypted_backup(parts, network, counts, captured, key):
    metadata = {'format': 1, 'captured_utc': captured.isoformat(), 'network': network, 'parts': {}}
    output = BytesIO()
    with ZipFile(output, 'w') as bundle:
        for name in recovery.PARTS:
            data = parts[name]
            detail = {'bytes': len(data), 'sha256': sha256(data).hexdigest()}
            if name in counts:
                detail['members'] = counts[name]
            metadata['parts'][name] = detail
            bundle.writestr(name, data)
        bundle.writestr('metadata.json', json.dumps(metadata))
    nonce = os.urandom(12)
    return recovery.MAGIC + nonce + AESGCM(key).encrypt(nonce, output.getvalue(), recovery.MAGIC)


def create(folder, destination, portable, authorize):
    if not (folder / 'operator.json').is_file():
        raise ValueError('Select an installed COLDWIRE operator folder')
    root = recovery.data_home()
    destination = (destination or root / 'backups').expanduser().resolve()
    if destination == folder or folder in destination.parents or root / 'backup-keys' == destination:
        raise ValueError('Choose a backup folder outside the operator folder and key store')
    key = AESGCM.generate_key(bit_length=256)
    if portable or os.name != 'nt':
        sealed, extension = recovery.seal_portable(key), '.key.cwkey'
    else:
        sealed, extension = recovery.seal_dpapi(key, protect=True), '.key.dpapi'
        if recovery.seal_dpapi(sealed) != key:
            raise ValueError('Windows could not re-open the protected key')
    parts, network, counts = collect(folder, authorize)
    now = datetime.now(timezone.utc)
    name = f'coldwire-{now:%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}'
    backup = destination / (name + '.cwbackup')
    temporary = backup.with_suffix('.partial')
    key_path = root / 'backup-keys' / (name + extension)
    backup.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    key_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    recovery.write_new(temporary, encrypted_backup(parts, network, counts, now, key))
    try:
        recovery.read_backup(temporary, key)
        recovery.write_new(key_path, sealed)
        try:
            temporary.rename(backup)
        except OSError:
            key_path.unlink()
            raise
    finally:
        temporary.unlink(missing_ok=True)
    return backup, key_path
