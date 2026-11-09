"""Pure AWG 3.1 configuration and export helpers shared by installer and tests."""
import base64
import copy
import json
import os
import re
import secrets
from convert_profile import convert, encode, change_endpoint

CONTAINER = "amnezia-awg2"
DNS = ("1.1.1.1", "1.0.0.1")
I1 = "<r 2><b 0x858000010001000000000669636c6f756403636f6d0000010001c00c000100010000105a00044d583737>"


def valid_key(value):
    if len(base64.b64decode(value, validate=True)) != 32:
        raise ValueError("Expected a 32-byte AWG key")
    return value


def parameters(header_key):
    # Match the official 5.1.0.6 installer/constants; content padding is explicitly enabled.
    return {
        "Jc": str(4 + secrets.randbelow(3)), "Jmin": "10", "Jmax": "50",
        "S1": "12", "S2": "12", "S3": "12", "S4": "12",
        "H1": "1", "H2": "2", "H3": "3", "H4": "4",
        "HeaderProtectionKey": valid_key(header_key), "ContentPaddingAddition": "10-100",
        "RekeyAfterTime": "100-120", "RekeyTimeout": "3-7", "RejectAfterTime": "150-180",
        "KeepaliveTimeout": "5-15", "MaxHandshakeAttempts": "15-20",
        "RandomTrailers": "on", "DisableCookies": "on",
    }


def server_config(state):
    lines = ["[Interface]", "Address = 10.8.1.1/24", "MTU = 1280",
             f"PrivateKey = {state['private_key']}", f"ListenPort = {state['port']}"]
    lines += [f"{k} = {v}" for k, v in state["parameters"].items()]
    lines += [f"# I1 = {I1}"]
    for client in state["clients"].values():
        lines += ["", "[Peer]", f"PublicKey = {client['public_key']}",
                  f"PresharedKey = {state['psk']}", f"AllowedIPs = {client['address']}/32"]
    return "\n".join(lines) + "\n"


def client_profile(state, name, private, public, address):
    params = state["parameters"]
    lines = ["[Interface]", f"Address = {address}/32", f"DNS = {', '.join(DNS)}",
             "MTU = 1280", f"PrivateKey = {private}"]
    lines += [f"{k} = {v}" for k, v in params.items()]
    lines += [f"I1 = {I1}", "", "[Peer]", f"PublicKey = {state['public_key']}",
              f"PresharedKey = {state['psk']}", "AllowedIPs = 0.0.0.0/0, ::/0",
              f"Endpoint = {state['endpoint']}:{state['port']}", "PersistentKeepalive = 25-35"]
    client = dict(params, I1=I1, config="\n".join(lines) + "\n", hostName=state["endpoint"],
                  port=state["port"], client_ip=address, client_priv_key=private, client_pub_key=public,
                  server_pub_key=state["public_key"], psk_key=state["psk"], clientId=public,
                  allowed_ips=["0.0.0.0/0", "::/0"], persistent_keep_alive="25-35", mtu="1280")
    awg = dict(params, I1=I1, I2="", I3="", I4="", I5="", port=str(state["port"]),
               transport_proto="udp", protocol_version="3.1", subnet_address="10.8.1.0", subnet_cidr="24",
               last_config=json.dumps(client, separators=(",", ":")))
    return {"format_version": 1, "containers": [{"container": CONTAINER, "awg": awg}], "defaultContainer": CONTAINER,
            "description": name, "dns1": DNS[0], "dns2": DNS[1], "hostName": state["endpoint"]}


def new_client(state, name, private, public):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}", name) or name in state["clients"]:
        raise ValueError("Client name must be new and contain only 1-48 letters, digits, - or _")
    used = {c["address"] for c in state["clients"].values()}
    address = next((f"10.8.1.{n}" for n in range(2, 255) if f"10.8.1.{n}" not in used), None)
    if address is None or any(public == c["public_key"] for c in state["clients"].values()):
        raise ValueError("Client address pool exhausted or duplicate key")
    result = copy.deepcopy(state)
    result["clients"][name] = {"address": address, "public_key": public}
    profile = client_profile(result, name, valid_key(private), valid_key(public), address)
    native = json.loads(profile["containers"][0]["awg"]["last_config"])["config"]
    files = {"client.vpn": encode(profile), "client.conf": native.encode()}
    if state.get("entry"):
        via = convert(profile, state["entry"], state["entry_port"])
        files["client-via-entry.vpn"] = encode(via)
        files["client-via-entry.conf"] = change_endpoint(native, state["endpoint"], state["port"], state["entry"], state["entry_port"]).encode()
    return result, files


def write_private(path, content):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(content if isinstance(content, bytes) else content.encode())


def public_binary_directory(path):
    # Secret-file umask must not make new executable directories inaccessible to DynamicUser.
    if not path.parent.exists():
        path.parent.mkdir(mode=0o755)
        path.parent.chmod(0o755)
    if not path.parent.stat().st_mode & 0o001:
        raise ValueError('Binary parent directory is not traversable; use a clean host')
    path.mkdir(mode=0o755)
    path.chmod(0o755)


def replace_private(path, content):
    temporary = path.with_name(path.name + ".tmp")
    write_private(temporary, content)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def save_state(directory, state):
    replace_private(directory / "awg0.conf", server_config(state))
    replace_private(directory / "server.json", json.dumps(state, indent=2) + "\n")
