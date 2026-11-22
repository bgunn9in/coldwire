"""Render the WAN firewall separately from the live relay and SPA client leases."""

from ipaddress import IPv4Address
import re


def settings(interface, peer, *ports):
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,15}', interface):
        raise ValueError('Invalid WAN interface')
    if not all(type(port) is int and 1 <= port <= 65535 for port in ports):
        raise ValueError('Invalid firewall port')
    return IPv4Address(peer)


def firewall(role, interface, peer, awg, ssh, spa=62201, relay=32497, retain_ssh=None, retain_awg=False):
    peer = settings(interface, peer, awg, ssh, spa, relay, *(() if retain_ssh is None else (retain_ssh,)))
    if role == 'entry':
        sets = 'set spa_admins { type ipv4_addr; flags timeout; size 4096; }'
        services = f'''meta nfproto ipv4 udp dport {spa} limit rate 100/second burst 50 packets accept
        meta nfproto ipv4 udp dport {spa} drop
        ip saddr @spa_admins tcp dport {ssh} accept
        meta nfproto ipv4 tcp dport {ssh} ct state established accept'''
        port_match = '' if retain_awg else f'ct original proto-dst {relay} '
        forwarding = f'ip daddr {peer} udp dport {awg} {port_match}ct status dnat accept'
    elif role == 'exit':
        sets = ''
        allowed = 'meta nfproto ipv4' if retain_awg else f'ip saddr {peer}'
        services = f'''{allowed} udp dport {awg} accept
        udp dport {awg} drop
        ip saddr {peer} tcp dport {ssh} accept'''
        forwarding = f'{allowed} meta l4proto udp ct original proto-dst {awg} ct status dnat accept'
    else:
        raise ValueError('Unknown node role')
    old = f'tcp dport {retain_ssh} accept' if retain_ssh else ''
    return f'''table inet coldwire_lockdown {{
    {sets}
    chain wan {{
        type filter hook input priority -6; policy accept;
        iifname != "{interface}" return
        ct state invalid drop
        udp sport 67 udp dport 68 meta nfproto ipv4 accept
        ip6 saddr fe80::/10 udp sport 547 udp dport 546 accept
        {services}
        ct direction reply ct state {{ established, related }} accept
        {old}
        icmp type {{ destination-unreachable, time-exceeded, parameter-problem }} accept
        icmpv6 type {{ destination-unreachable, packet-too-big, time-exceeded, parameter-problem }} accept
        ip6 hoplimit 255 icmpv6 type {{ nd-router-advert, nd-neighbor-solicit, nd-neighbor-advert }} accept
        counter drop
    }}
    chain forward_wan {{
        type filter hook forward priority -6; policy accept;
        iifname != "{interface}" return
        ct state invalid drop
        ct direction reply ct state {{ established, related }} accept
        {forwarding}
        counter drop
    }}
}}
'''


def admission_gate(interface, address, relay):
    address = settings(interface, address, relay)
    return f'''table inet coldwire_access {{
    set spa_clients {{ type ipv4_addr; flags timeout; size 4096; }}
    chain admission {{
        type filter hook prerouting priority -110; policy accept;
        iifname "{interface}" ip daddr {address} udp dport {relay} ip saddr != @spa_clients counter drop
    }}
}}
'''
