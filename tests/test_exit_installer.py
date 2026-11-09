import base64
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import install_exit as exit_tool
from convert_profile import awg_section, client_config, decode


def key(n):
    return base64.b64encode(bytes([n]) * 32).decode()


def state():
    return {"installer": exit_tool.MARKER, "wan_interface": "ens3", "endpoint": "198.51.100.20",
            "port": 32497, "entry": "203.0.113.10", "entry_port": 443,
            "private_key": key(1), "public_key": key(2), "psk": key(3),
            "parameters": exit_tool.parameters(key(4)), "clients": {}}


class ExitInstallerTests(unittest.TestCase):
    def test_parameters_require_awg31_and_fresh_hpk(self):
        params = exit_tool.parameters(key(4))
        self.assertIn(params["Jc"], {"4", "5", "6"})
        for n in range(1, 5):
            self.assertEqual(params[f"S{n}"], "12")
            self.assertEqual(params[f"H{n}"], str(n))
        for name in ("HeaderProtectionKey", "ContentPaddingAddition", "RekeyAfterTime", "RandomTrailers", "DisableCookies"):
            self.assertIn(name, params)
        with self.assertRaises(ValueError):
            exit_tool.parameters("invalid")

    def test_new_peer_direct_and_via_entry_profiles(self):
        original = state()
        before = copy.deepcopy(original)
        changed, files = exit_tool.new_client(original, "phone", key(5), key(6))
        self.assertEqual(original, before)
        self.assertEqual(changed["clients"]["phone"]["address"], "10.8.1.2")
        self.assertEqual(len(files), 4)
        direct = decode(files["client.vpn"])
        via = decode(files["client-via-entry.vpn"])
        self.assertNotIn("password", direct)
        self.assertEqual(direct["format_version"], 1)
        self.assertEqual(awg_section(direct)["protocol_version"], "3.1")
        direct_client = client_config(awg_section(direct))
        via_client = client_config(awg_section(via))
        self.assertEqual(via_client["hostName"], "203.0.113.10")
        self.assertEqual(via_client["port"], 443)
        self.assertEqual(direct_client["client_priv_key"], via_client["client_priv_key"])
        self.assertEqual(files["client-via-entry.conf"], files["client.conf"].replace(b"198.51.100.20:32497", b"203.0.113.10:443"))
        native = exit_tool.server_config(changed)
        self.assertIn("PublicKey = " + key(6), native)
        self.assertIn("AllowedIPs = 10.8.1.2/32", native)
        self.assertNotIn(key(5), native)

    def test_new_names_addresses_and_keys(self):
        changed, _ = exit_tool.new_client(state(), "phone", key(5), key(6))
        for name in ("phone", "../escape", "bad name", "", "x" * 49):
            with self.assertRaises(ValueError):
                exit_tool.new_client(changed, name, key(7), key(8))
        with self.assertRaises(ValueError):
            exit_tool.new_client(changed, "duplicate", key(7), key(6))
        next_state, _ = exit_tool.new_client(changed, "mac", key(7), key(8))
        self.assertEqual(next_state["clients"]["mac"]["address"], "10.8.1.3")

    def test_failed_peer_add_restores_existing_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            persistent = directory / "state"
            persistent.mkdir(parents=True)
            clients = directory / "clients"
            clients.mkdir()
            previous = state()
            exit_tool.save_state(persistent, previous)
            before = (persistent / "awg0.conf").read_bytes()
            changed, files = exit_tool.new_client(previous, "phone", key(5), key(6))
            def fail_add(*args, **kwargs):
                if args[-1] != "remove":
                    raise RuntimeError("simulated failed peer registration")
                return ""
            with patch.object(exit_tool, "STATE", persistent), patch.object(exit_tool, "CLIENTS", clients), patch.object(exit_tool, "run", fail_add):
                with self.assertRaises(RuntimeError):
                    exit_tool.issue_client(previous, changed, files, "phone")
            self.assertEqual(json.loads((persistent / "server.json").read_text()), previous)
            self.assertEqual((persistent / "awg0.conf").read_bytes(), before)

    def test_successful_peer_add_uses_stdin_for_psk(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            persistent = directory / "state"
            persistent.mkdir(parents=True)
            clients = directory / "clients"
            clients.mkdir()
            previous = state()
            changed, files = exit_tool.new_client(previous, "phone", key(5), key(6))
            with patch.object(exit_tool, "STATE", persistent), patch.object(exit_tool, "CLIENTS", clients), patch.object(exit_tool, "run", return_value="") as command:
                exit_tool.issue_client(previous, changed, files, "phone")
                args, kwargs = command.call_args
                self.assertNotIn(changed["psk"], args)
                self.assertEqual(kwargs["data"], changed["psk"] + "\n")
            self.assertEqual(json.loads((persistent / "server.json").read_text()), changed)

    def test_output_files_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "key"
            exit_tool.write_private(output, "original")
            with self.assertRaises(FileExistsError):
                exit_tool.write_private(output, "changed")
            self.assertEqual(output.read_text(), "original")

    def test_help_is_available_without_root_or_docker(self):
        result = subprocess.run([sys.executable, str(ROOT / "install_exit.py"), "install", "--help"], capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn(b"--endpoint", result.stdout)

    def test_preflight_refuses_docker_before_changes(self):
        args = SimpleNamespace(endpoint="93.184.216.34", entry=None, port=32497, entry_port=32497, client="test")
        calls = []
        def command(*parts, **kwargs):
            calls.append(parts)
            if parts == ("ip", "-j", "address"):
                return json.dumps([{"addr_info": [{"family": "inet", "local": args.endpoint}]}])
            if parts[0] == "ss":
                return ""
            if parts == ("docker", "ps", "-aq"):
                return "existing-container"
            self.fail("Unexpected command before refusal: " + repr(parts))
        with patch.object(Path, "read_text", return_value='ID=ubuntu\nVERSION_ID="22.04"\n'), \
             patch.object(Path, "is_dir", return_value=True), \
             patch.object(Path, "exists", autospec=True, side_effect=lambda p: str(p).replace("\\", "/") == "/dev/net/tun"), \
             patch.object(exit_tool.platform, "machine", return_value="x86_64"), \
             patch.object(exit_tool.shutil, "which", side_effect=lambda name: "/bin/docker" if name == "docker" else None), \
             patch.object(exit_tool, "run", command):
            with self.assertRaisesRegex(ValueError, "Existing Docker"):
                exit_tool.preflight(args)
        self.assertEqual(len(calls), 0)

    def test_untested_os_versions_are_refused_before_commands(self):
        args = SimpleNamespace(endpoint="1.1.1.1", entry=None, port=32497, entry_port=32497, client="test")
        for release in ('ID=ubuntu\nVERSION_ID="24.10"\n', 'ID=ubuntu\nVERSION_ID="26.10"\n', 'ID=ubuntu\nVERSION_ID="20.04"\n', 'ID=debian\nVERSION_ID="12"\n'):
            with self.subTest(release=release), patch.object(Path, 'read_text', return_value=release), patch.object(exit_tool, 'run') as command:
                with self.assertRaisesRegex(ValueError, 'Supported Ubuntu LTS releases'):
                    exit_tool.preflight(args)
                command.assert_not_called()

    def test_supported_lts_releases_share_the_same_host_check(self):
        for version in ('22.04', '24.04', '26.04'):
            with self.subTest(version=version), patch.object(Path, 'read_text', return_value=f'ID=ubuntu\nVERSION_ID="{version}"\n'), patch.object(Path, 'is_dir', return_value=True), patch.object(exit_tool.platform, 'machine', return_value='x86_64'):
                self.assertEqual(exit_tool.require_supported_ubuntu(), version)

    def test_unsupported_architecture_is_refused(self):
        with patch.object(Path, 'read_text', return_value='ID=ubuntu\nVERSION_ID="26.04"\n'), patch.object(exit_tool.platform, 'machine', return_value='aarch64'), self.assertRaisesRegex(ValueError, 'amd64 Ubuntu'):
            exit_tool.require_supported_ubuntu()

    def test_activation_failure_stops_only_its_service(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            calls = []
            def command(*parts, **kwargs):
                calls.append(parts)
                if parts[:3] == ("systemctl", "enable", "--now"):
                    raise RuntimeError("simulated startup failure")
                return ""
            with patch.object(exit_tool, "STATE", directory / "state"), \
                 patch.object(exit_tool, "UNIT", directory / "exit.service"), \
                 patch.object(exit_tool, "SYSCTL", directory / "exit.conf"), \
                 patch.object(exit_tool, "run", command):
                with self.assertRaises(RuntimeError):
                    exit_tool.activate(state())
            self.assertIn(("systemctl", "disable", "--now", exit_tool.SERVICE), calls)
            self.assertTrue((directory / "state/server.json").is_file())
            unit = (directory / "exit.service").read_text()
            self.assertIn("GOMAXPROCS=1 GOMEMLIMIT=96MiB", unit)
            self.assertNotIn("docker", unit)
            self.assertIn("CapabilityBoundingSet=CAP_NET_ADMIN", unit)
            self.assertFalse((directory / 'exit.conf').exists())

    def test_released_native_bundle_has_pinned_provenance(self):
        files = exit_tool.read_bundle(exit_tool.BUNDLE)
        self.assertTrue(files['awg'].startswith(b'\x7fELF'))
        self.assertTrue(files['amneziawg-go'].startswith(b'\x7fELF'))
        manifest = json.loads(files['manifest.json'])
        self.assertEqual(manifest['minimum_glibc'], '2.35')

    def test_low_udp_port_has_only_the_additional_required_capability(self):
        self.assertNotIn('CAP_NET_BIND_SERVICE', exit_tool.service_text(32497))
        self.assertIn('CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_BIND_SERVICE', exit_tool.service_text(443))

    def test_corrupted_native_bundle_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / exit_tool.BUNDLE.name
            checksum = archive.with_suffix('').with_suffix('.sha256')
            data = bytearray(exit_tool.BUNDLE.read_bytes())
            data[-1] ^= 1
            archive.write_bytes(data)
            checksum.write_bytes(exit_tool.BUNDLE.with_suffix('').with_suffix('.sha256').read_bytes())
            with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
                exit_tool.read_bundle(archive)
            checksum.write_text(hashlib.sha256(archive.read_bytes()).hexdigest())
            with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
                exit_tool.read_bundle(archive)

    def test_bundle_path_traversal_rejected_before_extraction(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Path(folder) / exit_tool.BUNDLE.name
            with tarfile.open(archive, 'w:gz') as target:
                info = tarfile.TarInfo('../../outside')
                info.size = 1
                target.addfile(info, io.BytesIO(b'x'))
            archive.with_suffix('').with_suffix('.sha256').write_text(hashlib.sha256(archive.read_bytes()).hexdigest())
            with patch.object(exit_tool, 'BUNDLE_SHA256', hashlib.sha256(archive.read_bytes()).hexdigest()), self.assertRaisesRegex(ValueError, 'Unexpected archive'):
                exit_tool.read_bundle(archive)

    def test_private_endpoint_is_an_explicit_vm_option(self):
        args = SimpleNamespace(endpoint='10.0.2.15', entry=None, port=32497, entry_port=32497, client='vm', allow_private_endpoint=False)
        with self.assertRaisesRegex(ValueError, 'public --endpoint'):
            exit_tool.preflight(args)
        args.endpoint = '239.0.0.1'
        args.allow_private_endpoint = True
        with self.assertRaisesRegex(ValueError, 'public --endpoint'):
            exit_tool.preflight(args)


if __name__ == "__main__":
    unittest.main()
