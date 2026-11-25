import ipaddress
import json
from pathlib import Path
import secrets
import tempfile
import unittest
from unittest.mock import patch
from base64 import b64encode

import coldwire_access as panel
import coldwire_admin_helper as helper
import legacy_profiles


class ClientAdminHelperTest(unittest.TestCase):
    def test_migrated_native_peer_keeps_its_reserved_address_and_key(self):
        public = b64encode(b'a' * 32).decode()
        psk = b64encode(b'b' * 32).decode()
        peer = f'[Peer]\nPublicKey = {public}\nPresharedKey = {psk}\nAllowedIPs = 10.8.1.2/32\n'
        header = '[Interface]\nListenPort = 32497\n\n'
        initial = header + peer
        with patch.object(legacy_profiles, 'read_config', return_value=initial), patch.object(legacy_profiles, 'apply') as apply:
            legacy_profiles.set_pause(None, None, public, True, native={})
            suspended = apply.call_args.args[3]
            self.assertEqual(list(legacy_profiles.paused_peers(suspended))[0][:2], (public, peer))
            self.assertNotIn('[Peer]', suspended)
        with patch.object(legacy_profiles, 'read_config', return_value=suspended), patch.object(legacy_profiles, 'apply') as apply:
            legacy_profiles.set_pause(None, None, public, False, native={})
            self.assertEqual(apply.call_args.args[3], initial)
            self.assertEqual(apply.call_args.args[5:], ('10.8.1.2/32', psk))

    def test_managed_routes_reserve_the_two_servers(self):
        manifest = {'ssh': [{'host': '192.168.76.10'}, {'host': '192.168.76.20'}]}
        for mode in ('ru-services', 'ru-direct', 'all'):
            with self.subTest(mode=mode):
                profile = {}
                panel.add_routing_policy(profile, mode, manifest)
                policy = profile['coldwireRouting']
                self.assertEqual(profile['format_version'], 2)
                self.assertEqual(policy['mode'], mode)
                networks = [ipaddress.IPv4Network(value) for value in policy['ipv4']]
                self.assertEqual(bool(networks), mode != 'all')
                for endpoint in manifest['ssh']:
                    self.assertFalse(any(ipaddress.IPv4Address(endpoint['host']) in network for network in networks))

    def test_operator_encryption_and_portable_restore(self):
        with tempfile.TemporaryDirectory() as base:
            directory = Path(base)
            owner = directory / 'operator'
            owner.mkdir()
            for name in ('operator.json', 'devices.json'):
                (owner / name).write_text('{}')
            for name in ('known_hosts', 'ssh', 'admin.key'):
                (owner / name).write_text('fixture-' + name)
            encrypted = directory / 'operator.bin'
            key = secrets.token_bytes(32)
            helper.seal_operator(owner, encrypted, key)
            self.assertNotIn(b'fixture-admin.key', encrypted.read_bytes())
            with self.assertRaises(ValueError):
                helper.unseal_operator(encrypted, directory / 'wrong-key', secrets.token_bytes(32))
            recovery = directory / 'recovery.cwoperator'
            password = 'test passphrase for the lab'
            helper.execute({'action': 'backup-operator', 'stateKey': key.hex(), 'output': str(recovery),
                            'passphrase': password}, encrypted, False)
            self.assertNotIn(b'fixture-admin.key', recovery.read_bytes())
            restored = directory / 'restored.bin'
            fresh_key = secrets.token_hex(32)
            with patch.object(panel, 'status'):
                response = helper.execute({'action': 'restore-operator', 'stateKey': fresh_key, 'source': str(recovery),
                                           'passphrase': password}, restored, False)
            self.assertTrue(response['installed'])
            self.assertEqual(helper.execute({'action': 'list', 'stateKey': fresh_key}, restored, False), {'devices': []})


if __name__ == '__main__':
    unittest.main()
