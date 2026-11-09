import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import install_xray as xray
import xray_config as config
import deploy
import convert_xray
from test_deploy import arguments


def state():
    return {'installer': xray.MARKER, 'endpoint': '198.51.100.20', 'entry': '203.0.113.10',
            'port': 443, 'entry_port': 8443, 'target': 'example.com:443', 'server_name': 'example.com',
            'private_key': 'synthetic-server-private', 'public_key': 'synthetic-client-credential', 'clients': {}}


class XrayTests(unittest.TestCase):
    def test_unsupported_lts_host_is_refused_before_commands(self):
        for version in ('24.10', '26.10'):
            with self.subTest(version=version), patch.object(Path, 'read_text', return_value=f'ID=ubuntu\nVERSION_ID="{version}"\n'), patch.object(xray, 'run') as command:
                with self.assertRaisesRegex(ValueError, 'Supported Ubuntu LTS releases'):
                    xray.preflight(None)
                command.assert_not_called()

    def test_exports_preserve_identity_and_never_export_private_server_key(self):
        original = state()
        changed, files = config.new_client(original, 'phone')
        self.assertEqual(original['clients'], {})
        self.assertEqual(len(files), 4)
        direct, via = json.loads(files['xray-client.json']), json.loads(files['xray-client-via-entry.json'])
        first, second = direct['outbounds'][0], via['outbounds'][0]
        self.assertEqual(first['settings']['vnext'][0]['users'], second['settings']['vnext'][0]['users'])
        self.assertEqual(second['settings']['vnext'][0]['address'], original['entry'])
        self.assertEqual(second['settings']['vnext'][0]['port'], 8443)
        self.assertEqual(first['streamSettings']['realitySettings'], second['streamSettings']['realitySettings'])
        self.assertNotIn(original['private_key'], ''.join(files.values()))
        self.assertNotIn('allowInsecure', ''.join(files.values()))
        more, _ = config.new_client(changed, 'mac')
        self.assertNotEqual(more['clients']['phone'], more['clients']['mac'])
        with self.assertRaises(ValueError):
            config.new_client(changed, 'phone')
        server = config.server_config(changed)
        self.assertEqual(server['inbounds'][0]['streamSettings']['security'], 'reality')
        self.assertEqual(server['routing']['rules'][0]['outboundTag'], 'blocked')
        self.assertIn('::/0',server['routing']['rules'][0]['ip'])
        self.assertEqual(server['dns']['queryStrategy'],'UseIPv4')

    def test_target_validation_prevents_shell_or_url_inputs(self):
        self.assertEqual(config.target('EXAMPLE.com:8443'), ('example.com', 8443))
        for invalid in ('https://example.com', 'example.com;id', 'example.com:0', '127.0.0.1', '*', 'example.com/path'):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                config.target(invalid)

    def test_native_json_conversion_preserves_all_non_endpoint_fields(self):
        _,files=config.new_client(state(),'test')
        original=json.loads(files['xray-client.json'])
        changed=convert_xray.convert(original,'192.0.2.42',9443)
        expected=copy.deepcopy(original)
        expected['outbounds'][0]['settings']['vnext'][0].update(address='192.0.2.42',port=9443)
        self.assertEqual(changed,expected)
        self.assertEqual(original,json.loads(files['xray-client.json']))
        invalid=copy.deepcopy(original);invalid['outbounds'].append(copy.deepcopy(invalid['outbounds'][0]))
        with self.assertRaises(ValueError):convert_xray.convert(invalid,'192.0.2.42',443)

    def test_verified_bundle_and_corruption(self):
        files = xray.read_bundle(xray.BUNDLE)
        self.assertTrue(files['xray'].startswith(b'\x7fELF'))
        self.assertEqual(json.loads(files['manifest.json'])['version'], xray.VERSION)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / xray.BUNDLE.name
            path.write_bytes(xray.BUNDLE.read_bytes()[:-1])
            path.with_suffix('').with_suffix('.sha256').write_text(xray.BUNDLE.with_suffix('').with_suffix('.sha256').read_text())
            with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
                xray.read_bundle(path)
            path.with_suffix('').with_suffix('.sha256').write_text(hashlib.sha256(path.read_bytes()).hexdigest())
            with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
                xray.read_bundle(path)

    def test_service_has_no_network_admin_and_private_credentials(self):
        unit = xray.service_text()
        self.assertIn('DynamicUser=yes', unit)
        self.assertIn('LoadCredential=config.json:', unit)
        self.assertIn('CAP_NET_BIND_SERVICE', unit)
        self.assertNotIn('CAP_NET_ADMIN', unit)
        self.assertNotIn('ip_forward', unit)
        self.assertIn('${CREDENTIALS_DIRECTORY}/config.json',unit)
        self.assertNotIn('%d/config.json',unit)

    def test_install_binary_on_clean_host_without_libexec_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            binary=Path(directory)/'missing-parent'/'xray-bin'
            with patch.object(xray,'BIN',binary), patch.object(xray,'run'), patch.object(xray,'read_bundle',return_value={'xray':b'synthetic executable'}), patch.object(xray.shutil,'copy2'):
                xray.prepare(xray.BUNDLE)
            self.assertEqual((binary/'xray').read_bytes(),b'synthetic executable')

    def test_both_never_confirms_if_reality_fails_after_successful_awg(self):
        calls = []
        class Fake:
            def __init__(self, server, *unused):
                self.server, self.stage, self.kit, self.host_fingerprint = server, None, '/tmp/kit', 'SHA256:test'
            def upload(self, *args): pass
            def promote(self): self.kit = deploy.REMOTE
            def close(self): pass
            def run(self, command, **unused):
                calls.append(command)
                if command == 'cat /etc/machine-id': return self.server.role.encode()
                if 'probe-relay.py' in command:
                    return json.dumps(dict(handshake=True, server_sees_entry=True, temporary_peer_removed=True)).encode()
                if 'probe-xray.py' in command: raise deploy.DeployError('simulated REALITY failure')
                return b''
        import contextlib, os
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, TEST_A_PW='synthetic', TEST_B_PW='synthetic'), patch.object(deploy, 'retrieve_profiles'), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            args = arguments(Path(directory)); args.protocol = 'both'
            with self.assertRaises(deploy.DeployError): deploy.deploy(args, Fake)
        self.assertTrue(any('probe-relay.py' in c for c in calls))
        self.assertTrue(any('probe-xray.py' in c for c in calls))
        self.assertFalse(any('confirm-entry.sh' in c for c in calls))

    def test_both_retains_downloaded_awg_if_reality_installation_fails(self):
        class Fake:
            def __init__(self,server,*unused):self.server,self.stage,self.kit=server,None,'/tmp/kit'
            def upload(self,*unused):pass
            def promote(self):self.kit=deploy.REMOTE
            def close(self):pass
            def run(self,command,**unused):
                if command=='cat /etc/machine-id':return self.server.role.encode()
                if 'install_xray.py install' in command and '--check-only' not in command:raise deploy.DeployError('simulated install failure')
                return b''
        def retrieve(remote,args,output,protocol=None):
            self.assertEqual(protocol,'awg');(output/'client.vpn').write_bytes(b'synthetic fallback')
        import contextlib,os
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,TEST_A_PW='synthetic',TEST_B_PW='synthetic'),patch.object(deploy,'retrieve_profiles',retrieve),contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            args=arguments(Path(directory));args.protocol='both'
            with self.assertRaises(deploy.DeployError):deploy.deploy(args,Fake)
            self.assertEqual((args.output/'client.vpn').read_bytes(),b'synthetic fallback')

    def test_wizard_port_443_ssh_uses_8443_without_changing_ssh(self):
        class Fake:
            def __init__(self,server,*unused):self.server,self.stage,self.kit,self.host_fingerprint=server,None,'/tmp/kit','SHA256:test'
            def upload(self,*unused):pass
            def promote(self):self.kit=deploy.REMOTE
            def close(self):pass
            def run(self,command,**unused):
                if command=='cat /etc/machine-id':return self.server.role.encode()
                if command=='ss -H -ltn "sport = :443"' and self.server.role=='entry':return b'occupied by test SSH'
                if 'probe-xray.py' in command:return json.dumps(dict(application_data=True,server_sees_entry=True,temporary_process_removed=True)).encode()
                return b''
        import contextlib,os
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,TEST_A_PW='synthetic',TEST_B_PW='synthetic'),patch.object(deploy,'retrieve_profiles'),contextlib.redirect_stdout(io.StringIO()):
            args=arguments(Path(directory));args.protocol='reality';args.entry_ssh_port=443
            deploy.deploy(args,Fake)
            self.assertEqual(args.entry_server.port,443)
            self.assertEqual(args.reality_entry_port,8443)
            self.assertEqual(args.reality_exit_port,443)

    def test_tls_probe_uses_supported_openssl_group_api(self):
        result=type('Result',(),{'returncode':0,'stdout':'ALPN protocol: h2\n'})()
        with patch.object(xray.subprocess,'run',return_value=result) as command:
            self.assertEqual(xray.choose_target('example.com'),('example.com:443','example.com'))
            self.assertIn('X25519',command.call_args[0][0])
            self.assertIn('-verify_return_error',command.call_args[0][0])
