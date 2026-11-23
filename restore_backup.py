"""Open COLDWIRE backups and restore an operator folder or an offline server disk."""

import argparse
from base64 import b64decode, b64encode
from contextlib import contextmanager
from getpass import getpass
from hashlib import sha256
from io import BytesIO
import json
import ntpath
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import subprocess
import sys
import tarfile
from zipfile import BadZipFile, ZipFile


MAGIC = b'COLDWIRE-BACKUP-1\0'
PORTABLE = b'COLDWIRE-RECOVERY-KEY-1\0'
PARTS = ('entry.tar.gz', 'exit.tar.gz', 'operator.tar.gz', 'COLDWIRE-Access-Panel.zip')
LIMIT = 256 * 1024 * 1024


def data_home():
    if os.name == 'nt':
        return Path(os.environ['LOCALAPPDATA']) / 'COLDWIRE'
    home = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')
    return (home if home.is_absolute() else Path.home() / '.local/share') / 'coldwire'


def seal_dpapi(blob, *, protect=False):
    if os.name != 'nt':
        raise ValueError('Open this DPAPI key in the original Windows profile or use a portable recovery key')
    action = 'Protect' if protect else 'Unprotect'
    try:
        result = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
             "$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.Security; "
             "$data=[Convert]::FromBase64String([Console]::In.ReadToEnd()); "
             f"$key=[Security.Cryptography.ProtectedData]::{action}($data,$null,'CurrentUser'); "
             '[Console]::Out.Write([Convert]::ToBase64String($key))'],
            input=b64encode(blob), capture_output=True, check=True, timeout=30)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        if protect:
            raise ValueError('Windows could not protect the backup key') from error
        raise ValueError('Windows could not unlock the key. Use the Windows profile that created the backup') from error
    return b64decode(result.stdout, validate=True)


def decrypt(key, nonce, ciphertext, header):
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    try:
        return AESGCM(key).decrypt(nonce, ciphertext, header)
    except (InvalidTag, ValueError) as error:
        raise ValueError('Decryption failed. Check the key or passphrase and file integrity') from error


def password_key(password, salt):
    from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

    return Scrypt(salt=salt, length=32, n=2**17, r=8, p=1).derive(password.encode())


def read_key(backup, path):
    if path is None:
        base = data_home() / 'backup-keys' / backup.stem
        windows = base.with_name(base.name + '.key.dpapi')
        portable = base.with_name(base.name + '.key.cwkey')
        path = portable if portable.is_file() or os.name != 'nt' else windows
    with path.open('rb') as stream:
        blob = stream.read(4097)
    if not blob or len(blob) > 4096:
        raise ValueError('Invalid recovery key file')
    if not blob.startswith(PORTABLE):
        return seal_dpapi(blob)
    offset = len(PORTABLE)
    if len(blob) != offset + 16 + 12 + 32 + 16:
        raise ValueError('Invalid portable recovery key')
    salt = blob[offset:offset+16]
    prefix = PORTABLE + salt
    key = password_key(getpass('Recovery passphrase: '), salt)
    return decrypt(key, blob[len(prefix):len(prefix)+12], blob[len(prefix)+12:], prefix)


def read_backup(path, key):
    with path.open('rb') as stream:
        raw = stream.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError('Backup exceeds the supported size')
    if not raw.startswith(MAGIC) or len(raw) < len(MAGIC) + 28:
        raise ValueError('Unknown or incomplete COLDWIRE backup')
    offset = len(MAGIC)
    plain = decrypt(key, raw[offset:offset+12], raw[offset+12:], MAGIC)
    try:
        with ZipFile(BytesIO(plain)) as bundle:
            expected = ('metadata.json', *PARTS)
            if sorted(bundle.namelist()) != sorted(expected) or sum(i.file_size for i in bundle.infolist()) > LIMIT:
                raise ValueError('Invalid backup contents')
            metadata = json.loads(bundle.read('metadata.json'))
            if metadata['format'] != 1:
                raise ValueError('Unsupported backup version')
            parts = {name: bundle.read(name) for name in PARTS}
            for name, data in parts.items():
                reference = metadata['parts'][name]
                if reference['bytes'] != len(data) or reference['sha256'] != sha256(data).hexdigest():
                    raise ValueError(f'Checksum mismatch for {name}')
    except (BadZipFile, KeyError, TypeError) as error:
        raise ValueError('Invalid authenticated backup') from error
    return metadata, parts


def write_new(path, data):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


@contextmanager
def output_folder(path):
    path = path.expanduser()
    path = path.parent.resolve(strict=True) / path.name
    path.mkdir(mode=0o700)
    try:
        if os.name == 'nt':
            script = (
                "$ErrorActionPreference='Stop'; "
                "$acl=[Security.AccessControl.DirectorySecurity]::new(); "
                "$acl.SetAccessRuleProtection($true,$false); "
                "$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User; "
                "$rule=[Security.AccessControl.FileSystemAccessRule]::new($sid,'FullControl',"
                "'ContainerInherit,ObjectInherit','None','Allow'); "
                "$acl.AddAccessRule($rule); "
                "[IO.Directory]::SetAccessControl($env:CW_RECOVERY_DESTINATION,$acl)"
            )
            try:
                subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                               env=dict(os.environ, CW_RECOVERY_DESTINATION=str(path)),
                               capture_output=True, check=True, timeout=30)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
                raise ValueError('Could not restrict access to the recovery folder') from error
        yield path
    except BaseException:
        if path.resolve() == path:
            shutil.rmtree(path)
        raise


def operator_members(archive):
    names = set()
    members = archive.getmembers()
    for item in members:
        path = PurePosixPath(item.name)
        if (not path.parts or path.is_absolute() or '..' in path.parts
                or any(ord(c) < 32 or c in '\\:<>"|?*' for c in item.name)
                or any(reserved_windows_name(part) for part in path.parts)
                or path.as_posix().casefold() in names or not (item.isdir() or item.isfile())):
            raise ValueError('Unsafe path or member in operator backup')
        names.add(path.as_posix().casefold())
    if not {'operator.json', 'known_hosts', 'ssh', 'admin.key'} <= {
        item.name for item in members if item.isfile() and item.size
    }:
        raise ValueError('Operator backup is missing credentials or deployment settings')
    if sum(item.size for item in members) > LIMIT:
        raise ValueError('Operator backup exceeds the supported size')
    return members


def restore_operator(payload, destination):
    with tarfile.open(fileobj=BytesIO(payload), mode='r:gz') as archive:
        members = operator_members(archive)
        with output_folder(destination) as folder:
            for item in members:
                target = folder / item.name
                if item.isdir():
                    target.mkdir(mode=0o700, parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    with archive.extractfile(item) as source:
                        write_new(target, source.read())


def reserved_windows_name(part):
    if hasattr(ntpath, 'isreserved'):
        return ntpath.isreserved(part)
    return part.endswith(('.', ' ')) or PureWindowsPath(part).is_reserved()


def export_nodes(metadata, parts, destination):
    with output_folder(destination) as folder:
        for name in ('entry.tar.gz', 'exit.tar.gz', 'COLDWIRE-Access-Panel.zip'):
            write_new(folder / name, parts[name])
        checksum = ''.join(f'{sha256(parts[name]).hexdigest()}  {name}\n' for name in ('entry.tar.gz', 'exit.tar.gz'))
        write_new(folder / 'SHA256SUMS', checksum.encode('ascii'))
        write_new(folder / 'network.json', json.dumps(metadata['network'], indent=2).encode())
        write_new(folder / Path(__file__).name, Path(__file__).read_bytes())


def seal_portable(key):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    password = getpass('New recovery passphrase (at least 16 characters): ')
    if len(password) < 16 or password != getpass('Repeat recovery passphrase: '):
        raise ValueError('The passphrase is too short or the entries differ')
    salt, nonce = os.urandom(16), os.urandom(12)
    header = PORTABLE + salt
    ciphertext = AESGCM(password_key(password, salt)).encrypt(nonce, key, header)
    return header + nonce + ciphertext


def portable_key(path, key):
    write_new(path, seal_portable(key))


def recover(args):
    key = read_key(args.backup, args.key)
    metadata, parts = read_backup(args.backup, key)
    if args.action == 'check':
        print(f'Backup verified. Created {metadata["captured_utc"]}.')
        for name in PARTS:
            print(f'{name} ({len(parts[name]):,} bytes)')
    else:
        destination = args.to
        if args.action == 'operator':
            restore_operator(parts['operator.tar.gz'], destination)
        elif args.action == 'export-nodes':
            export_nodes(metadata, parts, destination)
        else:
            portable_key(destination, key)
        print(f'Saved to {destination.expanduser().resolve()}')


def linux_member(name):
    path = PurePosixPath(name)
    return (not path.is_absolute() and '..' not in path.parts and
            (path.parts[:1] in (('etc',), ('opt',)) or path.parts[:2] in (('var', 'lib'), ('root', 'awg-relay-kit-clients'))
             or path.parts[:4] == ('usr', 'local', 'libexec', 'awg-relay-kit')))


def apply_node(role, root):
    if sys.platform != 'linux' or os.geteuid() != 0:
        raise ValueError('Run as root from a Linux rescue system')
    root = root.resolve(strict=True)
    if root.samefile('/') or not all((root / path).is_dir() for path in ('etc', 'opt', 'var/lib')):
        raise ValueError('Mount a prepared server disk and pass its root directory')
    if any((root / path).exists() and (Path('/') / path).exists() and (root / path).samefile(Path('/') / path)
           for path in ('etc', 'opt', 'var/lib', 'usr/local/libexec', 'root')):
        raise ValueError('The destination shares directories with the running system')
    if any((root / path).exists() for path in ('etc/coldwire-lockdown', 'var/lib/coldwire-native-exit',
                                               'var/lib/coldwire-spa-pilot')):
        raise ValueError('The destination already contains a COLDWIRE installation')
    bundle = Path(__file__).resolve().parent
    name = role + '.tar.gz'
    expected = dict(line.split(maxsplit=1)[::-1] for line in (bundle / 'SHA256SUMS').read_text().splitlines())
    with (bundle / name).open('rb') as stream:
        data = stream.read(LIMIT + 1)
    if len(data) > LIMIT or expected.get(name) != sha256(data).hexdigest():
        raise ValueError(f'Checksum mismatch for {name}')
    with tarfile.open(fileobj=BytesIO(data), mode='r:gz') as archive:
        members = archive.getmembers()
        links = {PurePosixPath(item.name) for item in members if item.issym() or item.islnk()}
        for item in members:
            path = PurePosixPath(item.name)
            file = root / item.name
            if (not linux_member(item.name) or any(parent in links for parent in path.parents)
                    or (item.islnk() and not linux_member(item.linkname))
                    or not (item.isdir() or item.isfile() or item.issym() or item.islnk())
                    or file.parent.resolve() != file.parent or (item.isdir() and file.is_symlink())
                    or (item.islnk() and (root / item.linkname).resolve() != root / item.linkname)):
                raise ValueError(f'Unsafe restore path {item.name}')
    subprocess.run(['tar', '--numeric-owner', '--same-owner', '--same-permissions',
                    '-xzf', '-', '-C', str(root)], input=data, check=True)
    print(f'Restored node {role} to {root}. Boot the recovered disk from the provider console.')


def parser_options(parser):
    parser.add_argument('action', choices=('check', 'operator', 'export-nodes', 'portable-key'))
    parser.add_argument('backup', type=Path)
    parser.add_argument('--key', type=Path, help='Explicit DPAPI or portable recovery key file')
    parser.add_argument('--to', type=Path, help='New destination folder or key file')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('role', choices=('entry', 'exit'))
    parser.add_argument('--root', type=Path, required=True, help='Mounted offline Linux system disk')
    args = parser.parse_args()
    try:
        apply_node(args.role, args.root)
    except (OSError, ValueError, tarfile.TarError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'COLDWIRE: {error}\n')


if __name__ == '__main__':
    main()
