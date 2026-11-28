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
        self.commands = []
        fixture = self

        class Entry:
            def run(self, command):
                fixture.commands.append(('entry', command))
                return json.dumps(fixture.spa).encode()

        class Exit:
            def run(self, command):
                fixture.commands.append(('exit', command))
                if command.endswith('public-key'):
                    return key(6).encode()
                if command.endswith('allowed-ips'):
                    return f'{key(3)}\t10.8.1.2/32\n'.encode()
                if 'cat -- /etc/native/awg0.conf' in command:
                    return f'[Interface]\n[Peer]\nPublicKey = {key(3)}\n'.encode()
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

    def use_pilot_and_migrated_exit(self):
        native = {'awg': '/opt/native/awg', 'config': '/etc/native/awg0.conf'}
        self.manifest.update(legacy_exit=False, pilot_spa=True, native_exit=native)
        (self.folder / 'operator.json').write_text(json.dumps(self.manifest))
        return native

    def test_manage_pairs_the_pilot_spa_with_the_migrated_config(self):
        native = self.use_pilot_and_migrated_exit()
        template = self.source.read_bytes()
        (self.folder / 'legacy-template.vpn').write_bytes(template)
        args = Namespace(folder=self.folder, action='add', name='guest', user=None)
        with patch.object(panel.legacy_profiles, 'add', return_value=(self.guest, key(3))) as add:
            panel.manage(args)
        self.assertEqual(add.call_args.args[2], template)
        self.assertEqual(add.call_args.kwargs['native'], native)
        self.assertEqual(self.register.call_args.args[-2:], (panel.PILOT_SPA, panel.PILOT_KEYS))
        profile = self.folder / 'guest.vpn'
        self.assertTrue(profile.is_file())
        with patch.object(panel.legacy_profiles, 'revoke') as revoke:
            args.action = 'revoke'
            panel.manage(args)
        self.assertEqual(revoke.call_args.args[2], key(3))
        self.assertEqual(revoke.call_args.kwargs['native'], native)
        self.assertEqual(self.register.call_args.args[-2:], (panel.PILOT_SPA, panel.PILOT_KEYS))
        self.assertFalse(profile.exists())
        self.assertEqual(self.spa['devices'], [])

    def test_import_checks_the_persistent_migrated_peer_and_updates_pilot_spa(self):
        self.use_pilot_and_migrated_exit()
        panel.import_profile(self.arguments())
        self.assertIn(('exit', '/opt/native/awg show awg0 public-key'), self.commands)
        self.assertIn(('entry', f'cat {panel.PILOT_KEYS}'), self.commands)
        self.assertEqual(self.register.call_args.args[-2:], (panel.PILOT_SPA, panel.PILOT_KEYS))
        self.assertNotIn('native_name', json.loads((self.folder/'devices.json').read_bytes())['migrated'])

    def test_failed_registry_write_revokes_the_new_native_peer_and_spa_key(self):
        native = self.use_pilot_and_migrated_exit()
        (self.folder / 'legacy-template.vpn').write_bytes(self.source.read_bytes())
        args = Namespace(folder=self.folder, action='add', name='guest', user=None)
        with (patch.object(panel.legacy_profiles, 'add', return_value=(self.guest, key(3))),
              patch.object(panel.legacy_profiles, 'revoke') as revoke,
              patch.object(panel, 'replace_private', side_effect=OSError('registry could not be saved'))):
            with self.assertRaisesRegex(OSError, 'registry could not be saved'):
                panel.manage(args)
        self.assertEqual(revoke.call_args.args[2], key(3))
        self.assertEqual(revoke.call_args.kwargs['native'], native)
        self.assertEqual(self.spa['devices'], [])
        self.assertFalse((self.folder / 'guest.vpn').exists())

    def test_pilot_spa_can_also_use_a_standard_managed_native_exit(self):
        self.assertEqual(panel.panel_backends({'pilot_spa': True}),
                         (False, None, panel.PILOT_SPA, panel.PILOT_KEYS))
        self.assertEqual(panel.panel_backends({'legacy_exit': True}),
                         (True, None, panel.PILOT_SPA, panel.PILOT_KEYS))

    def test_install_menu_transitions_to_device_management(self):
        manifest = self.folder / 'operator.json'
        manifest.unlink()

        def install(args):
            self.assertTrue(args.allow_private_endpoint)
            manifest.write_text(json.dumps(self.manifest))

        with (patch('builtins.input', side_effect=['1', '2', '0']),
              patch.object(panel, 'install', side_effect=install) as wizard,
              patch.object(panel, 'manage') as manage,
              patch('builtins.print')):
            panel.panel(Namespace(folder=self.folder, allow_private_endpoint=True))
        wizard.assert_called_once()
        self.assertEqual(manage.call_args.args[0].action, 'list')

    def test_recovery_menu_available_before_installing(self):
        (self.folder / 'operator.json').unlink()
        with (patch('builtins.input', side_effect=['10', '0']),
              patch.object(panel, 'recovery_menu') as recover, patch('builtins.print')):
            panel.panel(Namespace(folder=self.folder))
        recover.assert_called_once()

    def test_list_update_available_before_and_after_installing(self):
        for installed in (True, False):
            with self.subTest(installed=installed):
                if not installed:
                    (self.folder / 'operator.json').unlink()
                with (patch('builtins.input', side_effect=['12', '2', '', '0']),
                      patch.object(panel.update_lists, 'main', return_value=0) as update,
                      patch.object(panel, 'authorized') as ssh, patch('builtins.print')):
                    panel.panel(Namespace(folder=self.folder))
                update.assert_called_once_with(['--offline'])
                ssh.assert_not_called()

    def test_list_menu_retries_offline_only_with_consent(self):
        for answer in ('y', ''):
            with self.subTest(answer=answer):
                with (patch('builtins.input', side_effect=['', '"Previous lists"', answer]),
                      patch.object(panel.update_lists, 'main',
                                   side_effect=[panel.update_lists.ONLINE_SOURCE_FAILED, 0]) as update):
                    panel.lists_menu()
                arguments = [['--compare-with', 'Previous lists']]
                if answer == 'y':
                    arguments.append(['--compare-with', 'Previous lists', '--offline'])
                self.assertEqual([call.args[0] for call in update.call_args_list], arguments)

    def test_list_menu_can_include_dedicated_cdn(self):
        with (patch('builtins.input', side_effect=['3', '']),
              patch.object(panel.update_lists, 'main', return_value=0) as update):
            panel.lists_menu()
        update.assert_called_once_with(['--include-dedicated-cdn'])

    def test_migration_menu_requires_confirmation_for_changes(self):
        (self.folder / 'operator.json').write_text(json.dumps(self.manifest | {'legacy_exit': True}))
        choices = ['9', '2', 'n', '1', '4', 'y', '0', '0']
        with (patch('builtins.input', side_effect=choices), patch('builtins.print'),
              patch.object(panel, 'migrate_exit') as migrate):
            panel.panel(Namespace(folder=self.folder))
        self.assertEqual([call.args[0].action for call in migrate.call_args_list], ['status', 'rollback'])
        self.assertTrue(all(call.args[0].timeout == 600 for call in migrate.call_args_list))

    def test_ssh_ignores_paths_from_another_operator_computer(self):
        (self.folder / 'ssh_config').write_text('IdentityFile X:/other/computer')
        with patch.object(panel, 'admit'), patch.object(panel.shutil, 'which', return_value='ssh'):
            def invoke(args, cwd):
                self.assertTrue(cwd.samefile(self.folder))
                self.assertNotIn(' ', args[2])
                self.assertIn('IdentityFile ssh', (cwd / args[2]).read_text())
                self.assertIn('UserKnownHostsFile known_hosts', (cwd / args[2]).read_text())
                self.assertEqual(args[3:], ['-J', 'entry', 'exit'])
                return 0
            with patch.object(panel.subprocess, 'call', side_effect=invoke):
                self.assertEqual(panel.ssh(Namespace(folder=self.folder, node='exit', remote_command=[])), 0)
