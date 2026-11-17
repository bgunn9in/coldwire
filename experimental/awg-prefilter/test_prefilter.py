"""Offline checks for the separately built, Linux-only experimental binary."""
import base64
import json
import os
from pathlib import Path
import random
import struct
import subprocess
import tempfile
import unittest

from export_keys import export, wire_parameters

HERE = Path(__file__).resolve().parent
BINARY = Path(os.environ.get('PREFILTER_BINARY', str(HERE / 'prefilter'))).resolve()
VECTORS = json.loads((HERE / 'test-vectors.json').read_text())
WIRE_VECTORS = json.loads((HERE / 'test-wire-vectors.json').read_text())


def packet(payload):
    size = 28 + len(payload)
    return struct.pack('!BBHHHBBH4s4s', 0x45, 0, size, 0, 0, 64, 17, 0,
                       bytes([192, 168, 76, 30]), bytes([192, 168, 76, 10])) + \
        struct.pack('!HHHH', 45000, 32497, 8 + len(payload), 0) + payload


class PrefilterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.key = Path(self.temp.name) / 'keys'
        self.key.write_text('HeaderProtectionKey=' + VECTORS['header_key'] +
                            '\nServerPublicKey=' + VECTORS['server_public_key'] + '\n')
        self.key.chmod(0o600)

    def tearDown(self):
        self.temp.cleanup()

    def check(self, raw, accept, reason=None, original_length=None):
        args = ['--check'] if original_length is None else ['--check-prefix', str(original_length)]
        result = subprocess.run([str(BINARY), *args, str(self.key)], input=raw, capture_output=True)
        self.assertEqual(result.returncode, 0 if accept else 2, result.stderr.decode(errors='replace'))
        data = json.loads(result.stdout)
        self.assertEqual(data['accept'], accept)
        if reason:
            self.assertEqual(data['reason'], reason)

    def test_independent_chacha20_and_blake2s_vectors(self):
        for number, reason in [('1', 'init'), ('2', 'response'), ('3', 'cookie'), ('4', 'transport')]:
            with self.subTest(number=number):
                self.check(packet(bytes.fromhex(VECTORS[number])), True, reason)

    def test_random_trailers_preserve_handshake_mac(self):
        for number in ('1', '2'):
            self.check(packet(bytes.fromhex(VECTORS[number]) + bytes(range(256)) * 4), True)

    def test_modified_handshake_is_dropped(self):
        for number in ('1', '2'):
            raw = bytearray.fromhex(VECTORS[number])
            raw[30] ^= 1
            self.check(packet(raw), False, 'mac1')

    def test_prefix_copy_preserves_verdict_for_all_types_and_options(self):
        for number, reason in [('1', 'init'), ('2', 'response'), ('3', 'cookie'), ('4', 'transport')]:
            for options in (0, 40):
                for trailer in (0, 2048, 60000):
                    with self.subTest(number=number, options=options, trailer=trailer):
                        raw = bytearray(packet(bytes.fromhex(VECTORS[number]) + bytes(trailer)))
                        raw[0] = 0x45 + options // 4
                        raw[2:4] = struct.pack('!H', len(raw) + options)
                        raw = raw[:20] + bytes(options) + raw[20:]
                        self.check(raw, True, reason)
                        self.check(raw[:212], True, reason, original_length=len(raw))

    def test_prefix_copy_still_checks_mac_and_original_lengths(self):
        raw = bytearray(packet(bytes.fromhex(VECTORS['1']) + bytes(2048)))
        raw[58] ^= 1
        self.check(raw[:212], False, 'mac1', original_length=len(raw))
        for length in (0, 27, 43, 187, 211):
            self.check(raw[:length], False, 'malformed', original_length=len(raw))
        self.check(raw[:212], False, 'malformed', original_length=len(raw) + 1)
        self.check(raw, False, 'malformed', original_length=len(raw) - 1)

    def test_wrong_header_key_is_dropped(self):
        text = self.key.read_text().replace(VECTORS['header_key'], base64.b64encode(bytes(32)).decode())
        self.key.write_text(text)
        self.check(packet(bytes.fromhex(VECTORS['1'])), False, 'header')

    def test_wrong_server_key_is_dropped(self):
        text = self.key.read_text().replace(VECTORS['server_public_key'], base64.b64encode(bytes(32)).decode())
        self.key.write_text(text)
        self.check(packet(bytes.fromhex(VECTORS['1'])), False, 'mac1')

    def test_handshake_replay_is_not_authentication(self):
        raw = packet(bytes.fromhex(VECTORS['1']))
        self.check(raw, True)
        self.check(raw, True)

    def test_transport_tag_is_not_authenticated_here(self):
        raw = bytearray.fromhex(VECTORS['4'])
        raw[-1] ^= 1
        self.check(packet(raw), True, 'transport')

    def test_truncated_protocol_messages(self):
        for number in ('1', '2', '3', '4'):
            raw = bytes.fromhex(VECTORS[number])
            for length in (0, 11, 15, len(raw) - 1):
                self.check(packet(raw[:length]), False)

    def test_bad_ip_udp_and_fragments(self):
        original = bytearray(packet(bytes.fromhex(VECTORS['1'])))
        for offset, value in [(0, 0x65), (0, 0x44), (2, 1), (6, 0x20), (7, 1), (9, 6), (24, 255)]:
            with self.subTest(offset=offset, value=value):
                raw = original.copy(); raw[offset] = value
                self.check(raw, False, 'malformed')
        for length in range(28):
            self.check(original[:length], False, 'malformed')

    def test_ipv4_options_are_not_treated_as_payload(self):
        raw = bytearray(packet(bytes.fromhex(VECTORS['1'])))
        raw[0] = 0x46
        raw[2:4] = struct.pack('!H', len(raw) + 4)
        self.check(raw[:20] + bytes(4) + raw[20:], True, 'init')

    def test_random_payloads_and_junk_are_dropped(self):
        rng = random.Random(78144)
        for _ in range(128):
            self.check(packet(rng.randbytes(rng.randrange(0, 1800))), False)

    def test_key_file_permissions_and_symlink(self):
        self.key.chmod(0o644)
        result = subprocess.run([str(BINARY), '--check', str(self.key)], input=b'', capture_output=True)
        self.assertEqual(result.returncode, 1)
        self.key.chmod(0o600)
        link = self.key.with_name('link'); link.symlink_to(self.key)
        result = subprocess.run([str(BINARY), '--check', str(link)], input=b'', capture_output=True)
        self.assertEqual(result.returncode, 1)

    def test_bad_key_files_do_not_print_keys(self):
        original = self.key.read_text()
        for text in ('', original + '\n', original.replace('=', '!', 1), original.replace('AAEC', '!!!!')):
            self.key.write_text(text)
            result = subprocess.run([str(BINARY), '--check', str(self.key)], input=b'', capture_output=True)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn(VECTORS['header_key'].encode(), result.stderr + result.stdout)

    def test_export_only_lab_header_and_public_keys_without_overwrite(self):
        state = {'endpoint': '192.168.76.20', 'installer': 'awg-relay-kit-native-v1',
                 'parameters': {'HeaderProtectionKey': VECTORS['header_key']},
                 'public_key': VECTORS['server_public_key'], 'private_key': 'DO-NOT-EXPORT'}
        state['parameters'].update({'S' + str(i): '12' for i in range(1, 5)})
        state['parameters'].update({'H' + str(i): str(i) for i in range(1, 5)})
        output = self.key.with_name('exported')
        export(state, output)
        self.assertEqual(output.read_text(), self.key.read_text()+''.join(f'{k}={v}\n' for k,v in wire_parameters(state['parameters']).items()))
        self.assertNotIn('DO-NOT-EXPORT', output.read_text())
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError):
            export(state, output)
        for address in ('1.1.1.1', '127.0.0.1', '203.0.113.1'):
            with self.subTest(address=address), self.assertRaises(ValueError):
                export(dict(state, endpoint=address), self.key.with_name('refused'))
        state['parameters']['S4'] = '16'
        export(state, self.key.with_name('changed-padding'))

    def test_wire_validation_rejects_ambiguous_or_unusable_parameters(self):
        parameters={**{f'S{i}':'12' for i in range(1,5)},**{f'H{i}':str(i) for i in range(1,5)}}
        for key,value in [('S1','11'),('S2','65507'),('S3',True),('S4','-1'),
                          ('H1','2-10'),('H1','10-9'),('H4','4294967296'),('H2','-1'),
                          ('H3','1-2-3'),('RandomTrailers','maybe')]:
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):
                wire_parameters(parameters|{key:value})
        self.assertEqual(wire_parameters(parameters|{'H1':'0','H4':'4294967294-4294967295'})['H4'],'4294967294-4294967295')

    def test_upstream_go_vectors_for_padding_header_ranges_and_trailers(self):
        for case in WIRE_VECTORS['cases']:
            parameters=wire_parameters(case['parameters'])
            self.key.write_text('HeaderProtectionKey='+WIRE_VECTORS['header_key']+'\nServerPublicKey='+WIRE_VECTORS['server_public_key']+'\n'+''.join(f'{k}={v}\n' for k,v in parameters.items()))
            copied=max(68+int(parameters[f'S{i}'])+n for i,n in enumerate((132,76,4,4),1))
            for vector in case['packets']:
                number=vector['type'];payload=bytes.fromhex(vector['payload'])
                reason=('init','response','cookie','transport')[number-1]
                with self.subTest(case=case['name'],number=number,header=vector['header']):
                    raw=packet(payload)
                    self.check(raw,True,reason)
                    raw=packet(payload+bytes(2048))
                    allowed=parameters['RandomTrailers']=='1' or number==4
                    self.check(raw,allowed,reason if allowed else 'header')
                    self.check(raw[:copied],allowed,reason if allowed else 'header',original_length=len(raw))
                    if number<3:
                        damaged=bytearray(payload);damaged[int(parameters[f'S{number}'])+30]^=1
                        self.check(packet(damaged),False,'mac1')

    def test_c_wire_parser_rejects_partial_duplicate_and_invalid_settings(self):
        original=self.key.read_text()
        full=''.join(f'{k}={v}\n' for k,v in wire_parameters({**{f'S{i}':'12' for i in range(1,5)},**{f'H{i}':str(i) for i in range(1,5)}}).items())
        for value in ('S1=12\n',full+'S1=12\n',full+'Unknown=1\n',full.replace('S1=12','S1=11'),
                      full.replace('H1=1','H1=2-10'),full.replace('H1=1','H1=4294967296'),
                      full.replace('H1=1','H1=4-3'),full.replace('RandomTrailers=0','RandomTrailers=true')):
            self.key.write_text(original+value)
            result=subprocess.run([str(BINARY),'--check',str(self.key)],input=b'',capture_output=True)
            self.assertEqual(result.returncode,1)
            self.assertNotIn(VECTORS['header_key'].encode(),result.stdout+result.stderr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
