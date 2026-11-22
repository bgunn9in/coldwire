from argparse import Namespace
import base64
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from convert_profile import awg_section, client_config, decode, encode
from exit_config import client_profile

if importlib.util.find_spec('paramiko'):
    import coldwire_access as panel


def key(value):
    return base64.b64encode(bytes([value]) * 32).decode()


@unittest.skipUnless(importlib.util.find_spec('paramiko'), 'panel dependency is required')
class AccessPanelTests(unittest.TestCase):
    def setUp(self):
        sandbox = tempfile.TemporaryDirectory(prefix='coldwire operator ')
        self.addCleanup(sandbox.cleanup)
        self.folder = Path(sandbox.name)
        self.manifest = {'ssh': [{'role': 'entry', 'host': '192.0.2.10', 'port': 22222, 'user': 'root'},
                                  {'role': 'exit', 'host': '192.0.2.20', 'port': 22222, 'user': 'root'}],
                         'spa_port': 62201, 'awg_port': 32498}
        (self.folder / 'operator.json').write_text(json.dumps(self.manifest))
        (self.folder / 'devices.json').write_text('{}')
        (self.folder / 'admin.key').write_text('ff' * 32)
        state = {'parameters': {}, 'public_key': key(6), 'psk': key(4), 'endpoint': '192.0.2.20', 'port': 32497}
        self.guest = client_profile(state, 'test', key(2), key(3), '10.8.1.2')
        self.source = self.folder / 'Amnezia export.vpn'
        self.source.write_bytes(encode(self.guest))
        self.spa = {'cookie_key': 'aa' * 32, 'devices': [], 'admins': ['ff' * 32]}
        fixture = self

        class Entry:
            def run(self, command):
                return json.dumps(fixture.spa).encode()

        class Exit:
            def run(self, command):
                if command.endswith('public-key'):
                    return key(6).encode()
                if command.endswith('allowed-ips'):
                    return f'{key(3)}\t10.8.1.2/32\n'.encode()
                return json.dumps({key(3): 'native-peer-name'}).encode()

        @contextmanager
        def authorized(*_):
            yield Entry(), Exit()

        self.addCleanup(patch.stopall)
        patch.object(panel, 'authorized', authorized).start()
        self.register = patch.object(panel, 'register_file', side_effect=self.register_service).start()

    def register_service(self, _, config, *_args):
        self.spa = config

    def arguments(self, **overrides):
        return Namespace(**({'folder': self.folder, 'source': self.source, 'name': 'migrated',
                             'user': None, 'client_profile': None, 'output': None} | overrides))

    def test_import_preserves_the_original_and_reuses_its_admission(self):
        original = self.source.read_bytes()
        panel.import_profile(self.arguments())
        first = client_config(awg_section(decode((self.folder / 'migrated-coldwire.vpn').read_bytes())))
        self.assertEqual((first['hostName'], first['port']), ('192.0.2.10', 32498))
        self.assertEqual(first['client_priv_key'], key(2))
        self.assertEqual(first['client_pub_key'], key(3))
        self.assertEqual(first['psk_key'], key(4))
        self.assertEqual(self.source.read_bytes(), original)
        registry = json.loads((self.folder / 'devices.json').read_bytes())
        self.assertEqual(registry['migrated']['native_name'], 'native-peer-name')
        self.assertEqual(self.spa['devices'], [first['coldwireSpa']['key']])
        panel.import_profile(self.arguments(output=self.folder / 'second.vpn'))
        self.register.assert_called_once()
        with self.assertRaisesRegex(ValueError, 'already registered'):
            panel.import_profile(self.arguments(name='shadow'))

    def test_admin_without_client_data_uses_matching_guest(self):
        administrator = self.guest | {'userName': 'root', 'port': 22}
        del awg_section(administrator)['last_config']
        admin_path = self.folder / 'admin.vpn'
        admin_path.write_bytes(encode(administrator))
        panel.import_profile(self.arguments(source=admin_path, client_profile=self.source))
        result = decode((self.folder / 'migrated-coldwire.vpn').read_bytes())
        self.assertEqual((result['userName'], result['hostName'], result['port']), ('root', '192.0.2.20', 22))
        self.assertEqual(client_config(awg_section(result))['hostName'], '192.0.2.10')

    def test_reexport_of_existing_legacy_peer_keeps_the_same_spa_key(self):
        self.manifest['legacy_exit'] = True
        (self.folder / 'operator.json').write_text(json.dumps(self.manifest))
        assigned = '77' * 32
        self.spa['devices'].append(assigned)
        (self.folder / 'devices.json').write_text(json.dumps({'migrated': {'user': 'owner', 'spa': assigned, 'peer': key(3)}}))
        panel.import_profile(self.arguments())
        export = decode((self.folder / 'migrated-coldwire.vpn').read_bytes())
        self.assertEqual(client_config(awg_section(export))['coldwireSpa']['key'], assigned)
        self.register.assert_not_called()

    def test_ssh_ignores_paths_from_another_operator_computer(self):
        (self.folder / 'ssh_config').write_text('IdentityFile X:/other/computer')
        with patch.object(panel, 'admit'), patch.object(panel.shutil, 'which', return_value='ssh'):
            def invoke(args, cwd):
                self.assertEqual(cwd, self.folder)
                self.assertNotIn(' ', args[2])
                self.assertIn('IdentityFile ssh', (cwd / args[2]).read_text())
                self.assertIn('UserKnownHostsFile known_hosts', (cwd / args[2]).read_text())
                self.assertEqual(args[3:], ['-J', 'entry', 'exit'])
                return 0
            with patch.object(panel.subprocess, 'call', side_effect=invoke):
                self.assertEqual(panel.ssh(Namespace(folder=self.folder, node='exit', remote_command=[])), 0)
