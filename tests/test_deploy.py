import contextlib
import io
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import deploy

try:
    import paramiko
except ImportError:
    paramiko = None


def arguments(directory):
    return SimpleNamespace(entry='192.168.76.10', exit='192.168.76.20', entry_user='root', exit_user='operator',
                           entry_ssh_host=None, exit_ssh_host=None, entry_ssh_port=22, exit_ssh_port=22,
                           entry_password_env='TEST_A_PW', exit_password_env='TEST_B_PW',
                           entry_fingerprint=None, exit_fingerprint=None, entry_port=32497, exit_port=32497,
                           client='test', output=directory / 'output', known_hosts=directory / 'known_hosts',
                           accept_new_host_keys=True, allow_private_endpoint=True, non_interactive=True)


class DeploymentTests(unittest.TestCase):
    def test_credentials_not_in_repr_and_values_with_shell_characters_survive(self):
        secret = 'synthetic password $() ; " quotes'
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'TEST_A_PW': secret}):
            server = deploy.server_from_args(arguments(Path(folder)), 'entry')
            self.assertEqual(server.password, secret)
            self.assertNotIn(secret, repr(server))

    def test_private_and_multicast_addresses_are_explicitly_restricted(self):
        self.assertEqual(deploy.validate_address('10.0.0.2', True), '10.0.0.2')
        for address, lab in (('10.0.0.2', False), ('239.0.0.1', True), ('127.0.0.1', True)):
            with self.assertRaises(ValueError):
                deploy.validate_address(address, lab)

    def test_payload_is_explicit_allowlist_and_normalized(self):
        import tarfile
        with tarfile.open(fileobj=io.BytesIO(deploy.package(deploy.ENTRY_FILES)), mode='r:gz') as archive:
            self.assertEqual(set(archive.getnames()), set(deploy.ENTRY_FILES))
            for name in archive.getnames():
                self.assertNotIn(b'\r\n', archive.extractfile(name).read())

    def test_failed_probe_never_confirms_and_profiles_survive(self):
        calls = []
        class FakeRemote:
            def __init__(self, server, *unused):
                self.server, self.stage, self.kit = server, None, '/tmp/public-kit'
                self.host_fingerprint = 'SHA256:synthetic'
            def upload(self, payload):
                pass
            def promote(self):
                self.kit = deploy.REMOTE
            def close(self):
                pass
            def run(self, command, **kwargs):
                calls.append((self.server.role, command))
                if command == 'cat /etc/machine-id':
                    return self.server.role.encode()
                if '/probe-relay.py' in command:
                    raise deploy.DeployError('simulated failed probe')
                return b''
        def retrieve(remote, args, output, protocol=None):
            (output / 'client.vpn').write_bytes(b'synthetic direct fallback')
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'TEST_A_PW': 'synthetic-A', 'TEST_B_PW': 'synthetic-B'}), patch.object(deploy, 'retrieve_profiles', retrieve), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            args = arguments(Path(folder))
            with self.assertRaises(deploy.DeployError):
                deploy.deploy(args, FakeRemote)
            self.assertEqual((args.output / 'client.vpn').read_bytes(), b'synthetic direct fallback')
        self.assertFalse(any('confirm-entry.sh' in command for _, command in calls))
        self.assertTrue(any(role == 'entry' and 'install-entry.sh' in command for role, command in calls))

    def test_same_machine_refused_before_upload_or_install(self):
        class SameMachine:
            def __init__(self, *args):
                self.stage = None
            def run(self, *args):
                return b'same-machine-id'
            def close(self):
                pass
            def upload(self, *args):
                raise AssertionError('Upload must not happen')
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'TEST_A_PW': 'synthetic-A', 'TEST_B_PW': 'synthetic-B'}), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(deploy.DeployError, 'same machine'):
                deploy.deploy(arguments(Path(folder)), SameMachine)


@unittest.skipUnless(paramiko, 'Install requirements-deploy.txt on the operator PC to test SSH identity handling')
class HostKeyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.first = paramiko.RSAKey.generate(2048)
        cls.changed = paramiko.RSAKey.generate(2048)

    def test_first_contact_requires_optin_or_matching_pin_and_rotation_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'known_hosts'
            server = deploy.Server('entry', '203.0.113.10', '203.0.113.10', 22, 'root', 'synthetic-password', 'synthetic-sudo')
            with self.assertRaisesRegex(deploy.DeployError, 'unknown host key'):
                deploy.verify_host_key(path, server, self.first, False)
            deploy.verify_host_key(path, server, self.first, True)
            deploy.verify_host_key(path, server, self.first, False)
            with self.assertRaisesRegex(deploy.DeployError, 'changed'):
                deploy.verify_host_key(path, server, self.changed, True)
            server.fingerprint = deploy.fingerprint(self.changed)
            with self.assertRaisesRegex(deploy.DeployError, 'mismatch'):
                deploy.verify_host_key(path, server, self.first, True)


if __name__ == '__main__':
    unittest.main()
