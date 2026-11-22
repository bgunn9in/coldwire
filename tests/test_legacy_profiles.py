import base64
import unittest

from convert_profile import awg_section, client_config, encode
from exit_config import client_profile
from legacy_profiles import CONFIG, add, revoke


def key(index):
    return base64.b64encode(bytes([index]) * 32).decode()


class LegacyProfileTests(unittest.TestCase):
    class Relay:
        def __init__(self):
            self.commands = []
            self.config = ('[Interface]\nAddress = 10.8.1.1/24\n'
                           f'PrivateKey = {key(1)}\n\n[Peer]\nPublicKey = {key(2)}\n'
                           f'PresharedKey = {key(3)}\nAllowedIPs = 10.8.1.2/32\n')

        def run(self, command, **kwargs):
            self.commands.append(command)
            if command.endswith('show awg0 public-key'):
                return key(10).encode()
            if command.endswith('cat ' + CONFIG):
                return self.config.encode()
            if 'genkey' in command:
                return '\n'.join(key(i) for i in (4, 5, 6)).encode()
            return b''

    def test_add_and_revoke_keep_existing_peer(self):
        relay, uploads = self.Relay(), []
        def upload(_, name, content):
            uploads.append((name, content))
        source = {'parameters': {}, 'public_key': key(10), 'psk': key(3), 'endpoint': '192.0.2.1', 'port': 32497}
        template = encode(client_profile(source, 'test', key(7), key(2), '10.8.1.2'))
        original = relay.config
        result, public = add(relay, upload, template)
        self.assertEqual(public, key(5))
        self.assertTrue(uploads[0][1].startswith(original))
        self.assertEqual(client_config(awg_section(result))['client_ip'], '10.8.1.3')
        self.assertEqual(client_config(awg_section(result))['psk_key'], key(6))
        self.assertTrue(any('before.conf' in script and 'allowed-ips' in script for script in relay.commands))
        relay.config = uploads[0][1]
        revoke(relay, upload, public)
        self.assertEqual(uploads[-1][1].strip(), original.strip())
        self.assertTrue(any(f'peer {public} remove' in script for script in relay.commands))
