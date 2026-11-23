import argparse
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import tarfile
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from zipfile import ZipFile

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import restore_backup as recovery
import create_backup


def operator_tar(extra=()):
    raw = BytesIO()
    with tarfile.open(fileobj=raw, mode='w:gz') as archive:
        for name in ('operator.json', 'admin.key', 'ssh', 'known_hosts', *extra):
            data = b'test fixture'
            item = tarfile.TarInfo(name)
            item.size = len(data)
            archive.addfile(item, BytesIO(data))
    return raw.getvalue()


class RecoveryTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_open_original_format_and_reject_corruption_before_writing(self):
        parts = dict.fromkeys(recovery.PARTS, b'dummy')
        parts['operator.tar.gz'] = operator_tar()
        meta = {'format': 1, 'captured_utc': '2026-01-01T00:00:00+00:00',
                'parts': {name: {'sha256': sha256(data).hexdigest(), 'bytes': len(data)}
                          for name, data in parts.items()}}
        plaintext = BytesIO()
        with ZipFile(plaintext, 'w') as archive:
            archive.writestr('metadata.json', json.dumps(meta))
            for name, data in parts.items():
                archive.writestr(name, data)
        key, nonce = os.urandom(32), os.urandom(12)
        backup = self.root / 'test.cwbackup'
        encoded = recovery.MAGIC + nonce + AESGCM(key).encrypt(nonce, plaintext.getvalue(), recovery.MAGIC)
        backup.write_bytes(encoded)
        self.assertEqual(recovery.read_backup(backup, key), (meta, parts))
        backup.write_bytes(encoded[:-1] + bytes([encoded[-1] ^ 1]))
        destination = self.root / 'restored'
        with patch.object(recovery, 'read_key', return_value=key), self.assertRaisesRegex(ValueError, 'Decryption failed'):
            recovery.recover(argparse.Namespace(action='operator', backup=backup, key=None, to=destination))
        self.assertFalse(destination.exists())

    def test_operator_recovery_refuses_overwrite_and_unsafe_paths(self):
        destination = self.root / 'operator'
        recovery.restore_operator(operator_tar(), destination)
        self.assertEqual((destination / 'ssh').read_bytes(), b'test fixture')
        with self.assertRaises(FileExistsError):
            recovery.restore_operator(operator_tar(), destination)
        for path in ('../escape', 'NUL.txt', 'SSH', 'nested\\test'):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, 'Unsafe'):
                recovery.restore_operator(operator_tar([path]), self.root / 'unsafe')
        self.assertFalse((self.root / 'unsafe').exists())

    def test_portable_key_roundtrip_and_wrong_password(self):
        passphrase = 'portable key test phrase'
        path = self.root / 'recovery.key'
        key = os.urandom(32)
        with patch.object(recovery, 'getpass', return_value=passphrase):
            recovery.portable_key(path, key)
            self.assertNotIn(key, path.read_bytes())
            self.assertEqual(recovery.read_key(self.root / 'test.cwbackup', path), key)
        with patch.object(recovery, 'getpass', return_value='different password'), self.assertRaisesRegex(ValueError, 'Decryption failed'):
            recovery.read_key(self.root / 'test.cwbackup', path)

    def test_created_backup_uses_the_existing_restore_format(self):
        operator = self.root / 'operator'
        operator.mkdir()
        (operator / 'operator.json').write_text('{}')
        parts = dict.fromkeys(recovery.PARTS, b'fixture')
        parts['operator.tar.gz'] = operator_tar()
        with (
            patch.object(recovery, 'data_home', return_value=self.root / 'data'),
            patch.object(recovery, 'getpass', return_value='portable key test phrase'),
            patch.object(create_backup, 'collect', return_value=(parts, {}, {})),
        ):
            backup, key = create_backup.create(operator, None, True, None)
            self.assertEqual(key.name, backup.stem + '.key.cwkey')
            self.assertEqual(recovery.read_backup(backup, recovery.read_key(backup, None))[1], parts)
        self.assertEqual(sorted(f.suffix for f in backup.parent.iterdir()), ['.cwbackup'])
