"""Edit peer blocks in an existing Docker or migrated native AWG configuration."""

import base64
import hashlib
from ipaddress import IPv4Interface, ip_network
import json
import re
import secrets
import shlex

from convert_profile import awg_section, client_config, decode
from exit_config import valid_key


CONTAINER = 'amnezia-awg2'
AWG = f'docker exec -i {CONTAINER} awg'
CONFIG = '/opt/amnezia/awg/awg0.conf'
PAUSE_MARKER = '# COLDWIRE-PAUSED '


def blocks(text):
    header, *peers = re.split(r'(?=^\[Peer\][ \t]*\r?$)', text, flags=re.MULTILINE)
    if '[Interface]' not in header:
        raise ValueError('Invalid AWG configuration header')
    return header, peers


def fields(text):
    return dict((name.strip(), value.strip()) for name, value in re.findall(r'^([^#=\r\n]+)=(.*)$', text, re.MULTILINE))


def paused_peers(header):
    for line in header.splitlines(keepends=True):
        if line.startswith(PAUSE_MARKER):
            public, encoded = line.removeprefix(PAUSE_MARKER).split()
            peer = base64.b64decode(encoded, validate=True).decode()
            if (not peer.startswith('[Peer]\n') or fields(peer).get('PublicKey') != valid_key(public)
                    or len(blocks('[Interface]\n' + peer)[1]) != 1):
                raise ValueError('Invalid persisted paused peer')
            yield public, peer, line


def awg_command(native):
    return shlex.quote(native['awg']) if native else AWG


def read_config(remote, native):
    if native:
        config = shlex.quote(native['config'])
        return remote.run(f'test -f {config}; test ! -L {config}; cat -- {config}').decode()
    return remote.run(f'docker exec {CONTAINER} cat {CONFIG}').decode()


def apply(remote, upload, previous, desired, public, address=None, psk=None, *, native=None):
    nonce = secrets.token_hex(12)
    local = f'/etc/coldwire-lockdown/peer-{nonce}'
    staged = f'/opt/amnezia/awg/.peer-{nonce}'
    digest = hashlib.sha256(previous.encode()).hexdigest()
    public = valid_key(public)
    awg = awg_command(native)
    op = f'{awg} set awg0 peer {public} remove'
    check_runtime = ''
    if address is not None:
        address = IPv4Interface(address)
        valid_key(psk)
        op = f'{awg} set awg0 peer {public} preshared-key /dev/stdin allowed-ips {address} < {local}.psk'
        check_runtime = f'''if {awg} show awg0 allowed-ips | tr '\\t ,' '\\n' | grep -Fx {address} >/dev/null; then exit 1; fi'''
    try:
        upload(remote, local, desired)
        if psk is not None:
            upload(remote, local + '.psk', psk + '\n')
        if native:
            config = shlex.quote(native['config'])
            remote.run(f'''
exec 9>/run/coldwire-peer.lock; flock -x 9
config={config}
test -f "$config"; test ! -L "$config"
test "$(sha256sum -- "$config" | cut -d ' ' -f 1)" = {digest}
{check_runtime}
staged=$(mktemp -d --tmpdir="$(dirname -- "$config")" .coldwire-peer-XXXXXXXX)
trap 'rm -f -- "$staged/before.conf" "$staged/next.conf"; rmdir -- "$staged"' EXIT
cp -aT -- "$config" "$staged/before.conf"
install -m 600 {local} "$staged/next.conf"
mv -fT -- "$staged/next.conf" "$config"
if ! {op}; then
    mv -fT -- "$staged/before.conf" "$config"
    exit 1
fi
''')
        else:
            remote.run(f'''
exec 9>/run/coldwire-peer.lock; flock -x 9
test "$(docker exec {CONTAINER} sha256sum {CONFIG} | cut -d ' ' -f 1)" = {digest}
{check_runtime}
docker exec {CONTAINER} mkdir -m 700 {staged}
trap 'docker exec {CONTAINER} rm -rf {staged}' EXIT
docker cp {local} {CONTAINER}:{staged}/awg0.conf
docker exec {CONTAINER} chmod 600 {staged}/awg0.conf
docker exec {CONTAINER} awg-quick strip {staged}/awg0.conf >/dev/null
docker exec {CONTAINER} cp -p {CONFIG} {staged}/before.conf
docker exec {CONTAINER} mv -f {staged}/awg0.conf {CONFIG}
if ! {op}; then
    docker exec {CONTAINER} mv -f {staged}/before.conf {CONFIG}
    exit 1
fi
''')
    finally:
        remote.run(f'rm -f {local} {local}.psk', check=False)


def add(remote, upload, template, *, native=None):
    profile = decode(template)
    awg = awg_section(profile)
    client = client_config(awg)
    if {'userName', 'password', 'sshKey'} & profile.keys():
        raise ValueError('The profile template must be a guest export')
    command = awg_command(native)
    if valid_key(client['server_pub_key']) != remote.run(command + ' show awg0 public-key').decode().strip():
        raise ValueError('The profile template belongs to a different exit server')
    previous = read_config(remote, native)
    header, peers = blocks(previous)
    if native:
        link, = json.loads(remote.run('ip -j -4 address show dev awg0'))
        interface, = (IPv4Interface(f"{item['local']}/{item['prefixlen']}")
                      for item in link['addr_info'] if item['family'] == 'inet' and item['scope'] == 'global')
    else:
        interface = IPv4Interface(fields(header)['Address'])
    used = {interface.ip}
    reserved = peers + [peer for _, peer, _ in paused_peers(header)]
    configured = [network.strip() for peer in reserved for network in fields(peer)['AllowedIPs'].split(',')]
    running = remote.run(command + ' show awg0 allowed-ips').decode().splitlines()
    live = [network for line in running for network in line.replace(',', ' ').split()[1:] if network != '(none)']
    for network in configured + live:
        subnet = ip_network(network)
        if subnet.version == 4 and subnet.overlaps(interface.network):
            if subnet.prefixlen != 32:
                raise ValueError('Non-host peer routes need manual address allocation')
            used.add(subnet.network_address)
    if interface.network.num_addresses > 4096:
        raise ValueError('Manually configure the peer address pool')
    address = next((str(ip) for ip in interface.network.hosts() if ip not in used), '')
    if not address:
        raise ValueError('The peer address pool is full')
    private, public, psk = (valid_key(line) for line in remote.run(f'''
set +x
private=$({command} genkey)
printf '%s\\n' "$private"
printf '%s\\n' "$private" | {command} pubkey
{command} genpsk
''').decode().splitlines())
    entries = {'PrivateKey': private, 'Address': address + '/32', 'PresharedKey': psk}
    for field, value in entries.items():
        client['config'], count = re.subn(rf'(?m)^{field}\s*=.*$', f'{field} = {value}', client['config'])
        if count != 1:
            raise ValueError(f'Profile template has an unexpected {field} field')
    client.update(client_priv_key=private, client_pub_key=public, client_ip=address, psk_key=psk, clientId=public)
    awg['last_config'] = json.dumps(client, separators=(',', ':'))
    desired = previous.rstrip() + f'\n\n[Peer]\nPublicKey = {public}\nPresharedKey = {psk}\nAllowedIPs = {address}/32\n'
    apply(remote, upload, previous, desired, public, address + '/32', psk, native=native)
    return profile, public


def revoke(remote, upload, public, *, native=None):
    valid_key(public)
    previous = read_config(remote, native)
    header, peers = blocks(previous)
    for key, _, marker in paused_peers(header):
        if key == public:
            header = header.replace(marker, '', 1)
    remaining = [peer for peer in peers if fields(peer)['PublicKey'] != public]
    if header + ''.join(remaining) != previous:
        apply(remote, upload, previous, header + ''.join(remaining), public, native=native)
    else:
        remote.run(f'{awg_command(native)} set awg0 peer {public} remove')


def set_pause(remote, upload, public, paused, *, native):
    valid_key(public)
    previous = read_config(remote, native)
    header, peers = blocks(previous)
    marker = next(((peer, line) for key, peer, line in paused_peers(header) if key == public), None)
    active = next((peer for peer in peers if fields(peer)['PublicKey'] == public), None)
    if paused:
        if marker and active is None:
            remote.run(f'{awg_command(native)} set awg0 peer {public} remove')
            return
        if marker or active is None:
            raise ValueError('Unexpected state for this peer')
        encoded = base64.b64encode(active.replace('\r\n', '\n').encode()).decode()
        header = header.rstrip('\r\n') + '\n' + PAUSE_MARKER + public + ' ' + encoded + '\n\n'
        apply(remote, upload, previous, header + ''.join(p for p in peers if p != active), public, native=native)
        return
    if active and marker is None:
        return
    if active or marker is None:
        raise ValueError('Unexpected state for this peer')
    peer, line = marker
    configuration = fields(peer)
    address = IPv4Interface(configuration['AllowedIPs'])
    if address.network.prefixlen != 32 or any(
            address.ip in ip_network(network.strip())
            for entry in peers for network in fields(entry)['AllowedIPs'].split(',')):
        raise ValueError('Paused address is no longer available')
    desired = header.replace(line, '', 1) + ''.join(peers)
    apply(remote, upload, previous, desired.rstrip() + '\n\n' + peer, public, str(address),
          configuration['PresharedKey'], native=native)
