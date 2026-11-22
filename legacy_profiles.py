"""Manage panel-issued peers on an existing Amnezia AWG container."""

import hashlib
from ipaddress import IPv4Interface, ip_network
import json
import re
import secrets

from convert_profile import awg_section, client_config, decode
from exit_config import valid_key


CONTAINER = 'amnezia-awg2'
AWG = f'docker exec -i {CONTAINER} awg'
CONFIG = '/opt/amnezia/awg/awg0.conf'


def blocks(text):
    header, *peers = re.split(r'(?=^\[Peer\][ \t]*\r?$)', text, flags=re.MULTILINE)
    if '[Interface]' not in header:
        raise ValueError('Invalid AWG configuration header')
    return header, peers


def fields(text):
    return dict((name.strip(), value.strip()) for name, value in re.findall(r'^([^#=\r\n]+)=(.*)$', text, re.MULTILINE))


def apply(remote, upload, previous, desired, public, address=None, psk=None):
    nonce = secrets.token_hex(12)
    local = f'/etc/coldwire-lockdown/peer-{nonce}'
    staged = f'/opt/amnezia/awg/.peer-{nonce}'
    digest = hashlib.sha256(previous.encode()).hexdigest()
    public = valid_key(public)
    op = f'{AWG} set awg0 peer {public} remove'
    check_runtime = ''
    if address is not None:
        address = IPv4Interface(address)
        valid_key(psk)
        op = f'{AWG} set awg0 peer {public} preshared-key /dev/stdin allowed-ips {address} < {local}.psk'
        check_runtime = f'''if {AWG} show awg0 allowed-ips | tr '\\t ,' '\\n' | grep -Fx {address} >/dev/null; then exit 1; fi'''
    try:
        upload(remote, local, desired)
        if psk is not None:
            upload(remote, local + '.psk', psk + '\n')
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


def add(remote, upload, template):
    profile = decode(template)
    awg = awg_section(profile)
    client = client_config(awg)
    if {'userName', 'password', 'sshKey'} & profile.keys():
        raise ValueError('Legacy profile template must be a guest export')
    if valid_key(client['server_pub_key']) != remote.run(AWG + ' show awg0 public-key').decode().strip():
        raise ValueError('Legacy profile belongs to a different exit server')
    previous = remote.run(f'docker exec {CONTAINER} cat {CONFIG}').decode()
    header, peers = blocks(previous)
    interface = IPv4Interface(fields(header)['Address'])
    used = {interface.ip}
    configured = [network.strip() for peer in peers for network in fields(peer)['AllowedIPs'].split(',')]
    running = remote.run(AWG + ' show awg0 allowed-ips').decode().splitlines()
    live = [network for line in running for network in line.replace(',', ' ').split()[1:] if network != '(none)']
    for network in configured + live:
        subnet = ip_network(network)
        if subnet.version == 4 and subnet.overlaps(interface.network):
            if subnet.prefixlen != 32:
                raise ValueError('Non-host legacy peer routes need manual address allocation')
            used.add(subnet.network_address)
    if interface.network.num_addresses > 4096:
        raise ValueError('Manually configure the legacy peer address pool')
    address = next((str(ip) for ip in interface.network.hosts() if ip not in used), '')
    if not address:
        raise ValueError('Legacy peer address pool is full')
    private, public, psk = (valid_key(line) for line in remote.run(f'''
set +x
private=$({AWG} genkey)
printf '%s\\n' "$private"
printf '%s\\n' "$private" | {AWG} pubkey
{AWG} genpsk
''').decode().splitlines())
    entries = {'PrivateKey': private, 'Address': address + '/32', 'PresharedKey': psk}
    for field, value in entries.items():
        client['config'], count = re.subn(rf'(?m)^{field}\s*=.*$', f'{field} = {value}', client['config'])
        if count != 1:
            raise ValueError(f'Profile template has an unexpected {field} field')
    client.update(client_priv_key=private, client_pub_key=public, client_ip=address, psk_key=psk, clientId=public)
    awg['last_config'] = json.dumps(client, separators=(',', ':'))
    desired = previous.rstrip() + f'\n\n[Peer]\nPublicKey = {public}\nPresharedKey = {psk}\nAllowedIPs = {address}/32\n'
    apply(remote, upload, previous, desired, public, address + '/32', psk)
    return profile, public


def revoke(remote, upload, public):
    valid_key(public)
    previous = remote.run(f'docker exec {CONTAINER} cat {CONFIG}').decode()
    header, peers = blocks(previous)
    remaining = [peer for peer in peers if fields(peer)['PublicKey'] != public]
    if len(remaining) != len(peers):
        apply(remote, upload, previous, header + ''.join(remaining), public)
    else:
        remote.run(f'{AWG} set awg0 peer {public} remove')
