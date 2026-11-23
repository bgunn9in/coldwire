import contextlib
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import deploy

try:
    import paramiko
except ImportError:
    paramiko = None


class DeploymentTests(unittest.TestCase):
    def test_ssh_stdout_remains_open_after_exit_status(self):
        from unittest.mock import patch

        class Channel:
            closed = False
            eof_received = False
            buffered = False

            def recv_ready(self):
                return self.buffered

            def recv(self, _):
                self.buffered, self.eof_received = False, True
                return b'last bytes'

            def recv_stderr_ready(self):
                return False

            def exit_status_ready(self):
                return True

            def recv_exit_status(self):
                return 0

            def __getattr__(self, name):
                return lambda *args: None

        channel = Channel()
        remote = deploy.Remote.__new__(deploy.Remote)
        remote.root = True
        remote.transport = SimpleNamespace(open_session=lambda **kwargs: channel)
        with patch.object(deploy.time, 'sleep', side_effect=lambda _: setattr(channel, 'buffered', True)):
            self.assertEqual(remote.run('true'), b'last bytes')

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
        from convert_profile import encode
        from test_tools import fixture
        calls = []
        profile = encode(fixture())

        class FakeRemote:
            def __init__(self, role, address):
                self.server = SimpleNamespace(role=role, address=address)
                self.stage, self.kit = None, '/tmp/public-kit'

            def upload(self, payload):
                pass

            def promote(self):
                calls.append((self.server.role, 'promote'))
                self.kit = deploy.REMOTE

            def run(self, command, **kwargs):
                calls.append((self.server.role, command))
                if command.startswith('cat /root/'):
                    return profile
                if '/probe-relay.py' in command:
                    raise deploy.DeployError('simulated failed probe')
                return b''

        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            output = Path(folder) / 'output'
            entry = FakeRemote('entry', '192.168.76.10')
            exit_node = FakeRemote('exit', '198.51.100.20')
            with self.assertRaisesRegex(deploy.DeployError, 'simulated failed probe'):
                deploy.deploy(entry, exit_node, output, 32497, True)
            self.assertEqual((output / 'client.vpn').read_bytes(), profile)
        self.assertFalse(any('confirm-entry.sh' in command for _, command in calls))
        checks = [index for index, (_, cmd) in enumerate(calls) if cmd.endswith('--check-only') or 'AWG_PREFLIGHT_ONLY' in cmd]
        first_promote = calls.index(('entry', 'promote'))
        self.assertEqual(len(checks), 2)
        self.assertLess(max(checks), first_promote)


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
