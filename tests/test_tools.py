import copy
import hashlib
import ipaddress as ip
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import convert_profile as profiles
import update_lists as lists


def fixture(admin=False, cached=True):
    # Synthetic strings deliberately aren't usable VPN keys or login credentials.
    native = "[Interface]\r\nPrivateKey = synthetic-private\r\nH1 = 123\r\n[Peer]\r\nPublicKey = synthetic-server\r\nEndpoint = 198.51.100.20:32497  # keep\r\nAllowedIPs = 0.0.0.0/0\r\n"
    client = {"client_ip": "10.8.1.9", "client_priv_key": "synthetic-private", "client_pub_key": "synthetic-public", "server_pub_key": "synthetic-server", "psk_key": "synthetic-psk", "config": native, "hostName": "198.51.100.20", "port": 32497, "H1": "123", "allowed_ips": ["0.0.0.0/0", "::/0"]}
    awg = {"port": "32497", "H1": "123"}
    if cached:
        awg["last_config"] = json.dumps(client)
    result = {"hostName": "198.51.100.20", "description": "test", "containers": [{"container": "amnezia-awg2", "awg": awg}], "defaultContainer": "amnezia-awg2"}
    if admin:
        result.update(userName="synthetic-admin", password="synthetic-credential", port=22)
    return result


class ProfileTests(unittest.TestCase):
    def test_guest_keys_and_crlf_unchanged(self):
        original = fixture()
        before = copy.deepcopy(original)
        result = profiles.convert(original, "203.0.113.10", 443)
        self.assertEqual(original, before)
        self.assertEqual(result["hostName"], "203.0.113.10")
        self.assertEqual(profiles.awg_section(result)["port"], "443")
        old = profiles.client_config(profiles.awg_section(original))
        client = profiles.client_config(profiles.awg_section(result))
        self.assertEqual(client["config"], old["config"].replace("198.51.100.20:32497", "203.0.113.10:443"))
        for key in set(client) - {"hostName", "port", "config"}:
            self.assertEqual(client[key], old[key])
        self.assertEqual(profiles.decode(profiles.encode(result)), result)

    def test_admin_management_and_server_port_preserved(self):
        original = fixture(admin=True)
        result = profiles.convert(original, "203.0.113.10", 443)
        for key in ("hostName", "port", "userName", "password"):
            self.assertEqual(result[key], original[key])
        self.assertEqual(profiles.awg_section(result)["port"], "32497")
        self.assertEqual(profiles.client_config(profiles.awg_section(result))["port"], 443)

    def test_admin_needs_explicit_client(self):
        admin = fixture(admin=True, cached=False)
        with self.assertRaises(ValueError):
            profiles.convert(admin, "203.0.113.10", 32497)
        result = profiles.convert(admin, "203.0.113.10", 32497, fixture())
        self.assertEqual(result["userName"], admin["userName"])
        donor = fixture()
        profiles.awg_section(donor)["H1"] = "999"
        with self.assertRaises(ValueError):
            profiles.convert(admin, "203.0.113.10", 32497, donor)

    def test_bad_endpoints_and_container_rejected(self):
        for port in (0, 65536):
            with self.assertRaises(ValueError):
                profiles.convert(fixture(), "203.0.113.10", port)
        source = fixture()
        client = profiles.client_config(profiles.awg_section(source))
        client["config"] += "Endpoint = 198.51.100.20:32497\n"
        profiles.awg_section(source)["last_config"] = json.dumps(client)
        with self.assertRaises(ValueError):
            profiles.convert(source, "203.0.113.10", 32497)

    def test_inconsistent_guest_metadata_rejected(self):
        source = fixture()
        source["hostName"] = "192.0.2.10"
        with self.assertRaises(ValueError):
            profiles.convert(source, "203.0.113.10", 32497)
        source = fixture()
        source["containers"][0]["container"] = "amnezia-wg"
        with self.assertRaises(ValueError):
            profiles.convert(source, "203.0.113.10", 32497)

    def test_malformed_compression_rejected(self):
        import base64
        for packed in (b"x", struct.pack(">I", 4_000_001) + zlib.compress(b"{}"), struct.pack(">I", 2) + zlib.compress(b"{}") + b"trailing"):
            with self.assertRaises(ValueError):
                profiles.decode(b"vpn://" + base64.urlsafe_b64encode(packed))

    def test_cli_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.vpn"
            source.write_bytes(profiles.encode(fixture()))
            original = source.read_bytes()
            result = subprocess.run([sys.executable, str(ROOT / "convert_profile.py"), str(source), str(source), "--entry", "203.0.113.10"], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(source.read_bytes(), original)
            self.assertNotIn(b"synthetic-private", result.stdout + result.stderr)

    def test_cli_requires_entry_and_preserves_keys_for_custom_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / "input.vpn", Path(directory) / "output.vpn"
            original = fixture(admin=True)
            source.write_bytes(profiles.encode(original))
            command = [sys.executable, str(ROOT / "convert_profile.py"), str(source), str(output)]
            missing = subprocess.run(command, capture_output=True)
            self.assertEqual(missing.returncode, 2)
            self.assertFalse(output.exists())
            result = subprocess.run(command + ["--entry", "192.0.2.42", "--port", "4444"], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            expected = profiles.convert(original, "192.0.2.42", 4444)
            self.assertEqual(profiles.decode(output.read_bytes()), expected)
            self.assertEqual(source.read_bytes(), profiles.encode(original))


class ListTests(unittest.TestCase):
    def test_complement_boundaries(self):
        self.assertEqual(lists.complement([]), [ip.IPv4Network("0.0.0.0/0")])
        self.assertEqual(lists.complement([ip.IPv4Network("0.0.0.0/0")]), [])
        with self.assertRaises(ValueError):
            lists.complement([ip.IPv4Network("10.0.0.0/8")] * 2)

    def test_optimization_preserves_ru_and_protected_ranges(self):
        exact = list(map(ip.IPv4Network, ("10.0.0.0/8", "77.88.0.0/18")))
        protected = [ip.IPv4Network("1.1.1.0/24")]
        required = (ip.IPv4Address("8.8.8.8"),)
        result, added = lists.optimize(exact, protected, required, budget=20)
        self.assertTrue(all(lists.contains(result, n) for n in exact))
        self.assertTrue(all(not n.overlaps(protected[0]) for n in result))
        self.assertFalse(lists.contains(result, ip.IPv4Network("8.8.8.8/32")))
        self.assertEqual(added, sum(n.num_addresses for n in result) - sum(n.num_addresses for n in exact))
        with self.assertRaises(ValueError):
            lists.optimize(exact, protected, required, budget=0)

    def test_reproduces_both_bundled_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "lists"
            result = subprocess.run([sys.executable, str(ROOT / "update_lists.py"), "--offline", "--output", str(output)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(list(output.iterdir())), 2)
            for name, size in (("ru-direct", 1097), ("ru-services", 77)):
                filename = f"{name}.amnezia.json"
                self.assertEqual((output / filename).read_bytes(), (ROOT / filename).read_bytes())
                self.assertEqual(len(json.loads((output / filename).read_bytes())), size)
            before = {p.name: p.read_bytes() for p in output.iterdir()}
            result = subprocess.run([sys.executable, str(ROOT / "update_lists.py"), "--offline", "--output", str(output)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(before, {p.name: p.read_bytes() for p in output.iterdir()})

    def test_checked_lists_avoid_sensitive_destinations(self):
        for name in ("ru-direct", "ru-services"):
            values = json.loads((ROOT / f"{name}.amnezia.json").read_bytes())
            nets = [ip.IPv4Network(e["ip"]) for e in values]
            self.assertEqual(nets, lists.collapse(nets))
            self.assertEqual(len(values), len({e["hostname"] for e in values}))
            self.assertTrue(all(e["hostname"].endswith(".invalid") for e in values))
            for a in ("1.1.1.1", "1.0.0.1", "8.8.8.8", "149.154.167.51"):
                self.assertFalse(lists.contains(nets, ip.IPv4Network(f"{a}/32")), (name, a))
            self.assertTrue(lists.contains(nets, ip.IPv4Network("77.88.55.88/32")))

    def test_vpn_only_addresses_are_kept_in_tunnel(self):
        exact = lists.read_networks(ROOT / "data/ru-networks.txt")
        bundled = [ip.IPv4Network(e["ip"]) for e in json.loads((ROOT / "ru-direct.amnezia.json").read_bytes())]
        candidates = list(dict.fromkeys(
            a for n in bundled for a in (n.network_address, n.broadcast_address)
            if a.is_global and not a.is_multicast and not lists.contains(exact, ip.IPv4Network(f"{a}/32"))
        ))[:2]
        self.assertEqual(len(candidates), 2)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "vpn-only"
            command = [sys.executable, str(ROOT / "update_lists.py"), "--offline", "--output", str(output),
                       "--entry", "198.51.100.10", "--exit", "203.0.113.20"]
            for address in candidates + candidates[:1]:
                command.extend(["--vpn-only", str(address)])
            result = subprocess.run(command, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual({p.name for p in output.iterdir()},
                             {"ru-direct.amnezia.json", "ru-services.amnezia.json"})
            for name, budget in (("ru-direct", 2010), ("ru-services", 1000)):
                networks = [ip.IPv4Network(e["ip"]) for e in
                            json.loads((output / f"{name}.amnezia.json").read_bytes())]
                for address in candidates + [ip.IPv4Address("198.51.100.10"), ip.IPv4Address("203.0.113.20")]:
                    self.assertFalse(lists.contains(networks, ip.IPv4Network(f"{address}/32")))
                self.assertLessEqual(lists.legacy_routes(networks), budget)
                if name == "ru-direct":
                    self.assertTrue(all(lists.contains(networks, n) for n in exact))

    def test_vpn_only_rejects_invalid_or_ru_addresses_without_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "refused"
            for address in ("not-an-ip", "::1", "1.1.1.0/24", "77.88.55.88", "192.168.1.1"):
                with self.subTest(address=address):
                    result = subprocess.run([sys.executable, str(ROOT / "update_lists.py"), "--offline",
                                             "--output", str(output), "--vpn-only", address], capture_output=True)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(output.exists())

    def test_optional_protected_endpoint_changes_lists_and_conflicts_fail_safely(self):
        exact = lists.read_networks(ROOT / "data/ru-networks.txt")
        bundled = [ip.IPv4Network(e["ip"]) for e in json.loads((ROOT / "ru-direct.amnezia.json").read_bytes())]
        candidate = next(a for n in bundled for a in (n.network_address, n.broadcast_address)
                         if a.is_global and not a.is_multicast and not lists.contains(exact, ip.IPv4Network(f"{a}/32")))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "protected"
            command = [sys.executable, str(ROOT / "update_lists.py"), "--offline", "--output", str(output)]
            result = subprocess.run(command + ["--entry", str(candidate)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            protected = [ip.IPv4Network(e["ip"]) for e in json.loads((output / "ru-direct.amnezia.json").read_bytes())]
            self.assertFalse(lists.contains(protected, ip.IPv4Network(f"{candidate}/32")))
            self.assertTrue(all(lists.contains(protected, n) for n in exact))
            self.assertEqual(len(list(output.iterdir())), 2)
            failed_output = Path(directory) / "conflict"
            result = subprocess.run([sys.executable, str(ROOT / "update_lists.py"), "--offline",
                                     "--output", str(failed_output), "--entry", "77.88.55.88"], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(failed_output.exists())


if __name__ == "__main__":
    unittest.main()
