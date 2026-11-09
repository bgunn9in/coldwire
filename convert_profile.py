#!/usr/bin/env python3
"""Change the VPN endpoint without changing registered keys or admin SSH access."""
import argparse
import base64
import copy
import ipaddress
import json
import os
from pathlib import Path
import re
import struct
import sys
import zlib

LIMIT = 4_000_000


def decode(raw):
    if len(raw) > LIMIT * 2:
        raise ValueError("Profile is too large")
    text = raw.decode("utf-8-sig").strip()
    if not text.startswith("vpn://"):
        raise ValueError("Expected an Amnezia vpn:// export, not a settings backup")
    encoded = text[6:]
    packed = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True)
    if len(packed) < 6:
        raise ValueError("Truncated qCompress header")
    expected = struct.unpack(">I", packed[:4])[0]
    if not 0 < expected <= LIMIT:
        raise ValueError("Invalid uncompressed size")
    inflater = zlib.decompressobj()
    data = inflater.decompress(packed[4:], expected + 1)
    if len(data) != expected or not inflater.eof or inflater.unused_data:
        raise ValueError("Invalid compressed payload")
    result = json.loads(data)
    if not isinstance(result, dict):
        raise ValueError("Expected a JSON object")
    return result


def encode(config):
    data = json.dumps(config, ensure_ascii=False, separators=(",", ":")).encode()
    if len(data) > LIMIT:
        raise ValueError("Profile is too large")
    return b"vpn://" + base64.urlsafe_b64encode(struct.pack(">I", len(data)) + zlib.compress(data)).rstrip(b"=") + b"\n"


def awg_section(profile):
    containers = profile.get("containers", [])
    if len(containers) != 1 or containers[0].get("container") != "amnezia-awg2":
        raise ValueError("Only a single amnezia-awg2 container is supported")
    if profile.get("defaultContainer") != "amnezia-awg2":
        raise ValueError("Unexpected default protocol")
    return containers[0]["awg"]


def client_config(awg):
    value = awg.get("last_config")
    if not value:
        raise ValueError("No client last_config; export a working client and pass --client-profile")
    result = json.loads(value) if isinstance(value, str) else value
    if not isinstance(result, dict):
        raise ValueError("Invalid client last_config")
    for name in ("client_ip", "client_priv_key", "client_pub_key", "server_pub_key", "psk_key", "config", "hostName", "port"):
        if not result.get(name):
            raise ValueError("Missing required client field: " + name)
    return result


def check_guest_endpoint(profile, awg, client):
    if profile.get("hostName") != client["hostName"] or str(awg.get("port")) != str(client["port"]):
        raise ValueError("Guest endpoint metadata is inconsistent")


def change_endpoint(native, old_host, old_port, entry, port):
    # Preserve CRLF, comments, keys, obfuscation parameters and every unrelated line.
    pattern = re.compile(r"^([ \t]*Endpoint[ \t]*=[ \t]*)([^\r\n#;]+?)([ \t]*(?:[#;][^\r\n]*)?)(\r?)$", re.MULTILINE)
    matches = list(pattern.finditer(native))
    if len(matches) != 1 or matches[0][2].strip() != f"{old_host}:{old_port}":
        raise ValueError("Expected exactly one Endpoint matching client metadata")
    return pattern.sub(lambda m: f"{m[1]}{entry}:{port}{m[3]}{m[4]}", native)


def convert(profile, entry, port, donor=None):
    ipaddress.IPv4Address(entry)
    if not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    result = copy.deepcopy(profile)
    awg = awg_section(result)
    admin = "userName" in result or "password" in result or "sshKey" in result
    if donor is not None:
        if not admin:
            raise ValueError("--client-profile is only for an administrator export")
        donor_awg = awg_section(donor)
        if donor.get("hostName") != result.get("hostName"):
            raise ValueError("Client donor must be a direct export from the same exit server")
        # Compare server parameters, not credentials. Never guess a peer for an admin export.
        server_fields = (set(awg) | set(donor_awg)) - {"last_config"}
        if any(awg.get(k) != donor_awg.get(k) for k in server_fields):
            raise ValueError("Client and administrator server/protocol parameters differ")
        client = copy.deepcopy(client_config(donor_awg))
        check_guest_endpoint(donor, donor_awg, client)
        if awg.get("last_config") and client_config(awg)["server_pub_key"] != client["server_pub_key"]:
            raise ValueError("Donor and cached administrator server public keys differ")
    else:
        client = copy.deepcopy(client_config(awg))
        if not admin:
            check_guest_endpoint(result, awg, client)
    old_client = copy.deepcopy(client)
    client["config"] = change_endpoint(client["config"], client["hostName"], client["port"], entry, port)
    client.update(hostName=entry, port=port)
    if {k: v for k, v in client.items() if k not in {"hostName", "port", "config"}} != {
        k: v for k, v in old_client.items() if k not in {"hostName", "port", "config"}
    }:
        raise ValueError("Unexpected client mutation")
    awg["last_config"] = json.dumps(client, ensure_ascii=False, separators=(",", ":"))
    if not admin:
        result["hostName"] = entry
        awg["port"] = str(port)
    result["description"] = str(result.get("description", "AmneziaWG")) + f" via entry {entry}:{port}"
    if admin and (result["hostName"] != profile["hostName"] or awg["port"] != awg_section(profile)["port"]):
        raise ValueError("Administrator SSH/server endpoint was changed")
    if decode(encode(result)) != result:
        raise ValueError("Profile round-trip verification failed")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path, help="New file; existing files are never overwritten")
    parser.add_argument("--entry", required=True, help="Your entry server IPv4 address")
    parser.add_argument("--port", type=int, default=32497)
    parser.add_argument("--client-profile", type=Path, help="Working direct client export for an admin export without last_config")
    args = parser.parse_args()
    try:
        profile = decode(args.input.read_bytes())
        donor = decode(args.client_profile.read_bytes()) if args.client_profile else None
        payload = encode(convert(profile, args.entry, args.port, donor))
        # O_EXCL prevents overwriting the original, including through a symlink.
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
        print(f"Created {args.output}; VPN endpoint {args.entry}:{args.port}; original preserved")
    except (OSError, ValueError, KeyError, TypeError, zlib.error) as error:
        # Parser errors can contain source data; do not dump profiles or JSON fragments.
        print(f"Conversion failed ({type(error).__name__}). Check the input format, matching exports and a new output path. See docs/profiles.md.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
