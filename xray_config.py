"""VLESS/REALITY profiles; no private server key is ever exported to a client."""
import copy
import ipaddress
import json
import re
import secrets
from urllib.parse import urlencode, quote
import uuid

PRIVATE = ['0.0.0.0/8', '10.0.0.0/8', '100.64.0.0/10', '127.0.0.0/8', '169.254.0.0/16',
           '172.16.0.0/12', '192.168.0.0/16', '224.0.0.0/4', '240.0.0.0/4', '::/0']


def target(value):
    host, separator, port = value.partition(':')
    if not re.fullmatch(r'(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}', host):
        raise ValueError('REALITY target must be a DNS hostname, optionally :port')
    port = int(port) if separator else 443
    if not 1 <= port <= 65535:
        raise ValueError('Invalid target port')
    return host.lower(), port


def server_config(state):
    clients = [{'id': c['id'], 'flow': 'xtls-rprx-vision'} for c in state['clients'].values()]
    # No geoip/geosite database is needed for explicit private-address exclusions.
    rules = [{'type': 'field', 'ip': PRIVATE, 'outboundTag': 'blocked'}]
    return {'log': {'loglevel': 'warning', 'access': 'none'},
            'dns': {'queryStrategy': 'UseIPv4', 'servers': ['localhost']},
            'inbounds': [{'listen': state['endpoint'], 'port': state['port'], 'protocol': 'vless',
                          'settings': {'clients': clients, 'decryption': 'none'},
                          'streamSettings': {'network': 'tcp', 'security': 'reality', 'realitySettings': {
                              'show': False, 'target': state['target'], 'serverNames': [state['server_name']],
                              'privateKey': state['private_key'], 'shortIds': [c['short_id'] for c in state['clients'].values()],
                              'maxTimeDiff': 60000}}}],
            'outbounds': [{'tag': 'internet', 'protocol': 'freedom', 'streamSettings': {'sockopt': {'domainStrategy': 'UseIPv4'}}},
                          {'tag': 'blocked', 'protocol': 'blackhole'}],
            'routing': {'domainStrategy': 'IPIfNonMatch', 'rules': rules}}


def client_config(state, client, host=None, port=None):
    host, port = host or state['endpoint'], port or state['port']
    ipaddress.IPv4Address(host)
    return {'log': {'loglevel': 'warning'},
            'inbounds': [{'listen': '127.0.0.1', 'port': 10808, 'protocol': 'socks', 'settings': {'udp': True}}],
            'outbounds': [{'tag': 'proxy', 'protocol': 'vless',
                           'settings': {'vnext': [{'address': host, 'port': port,
                                                  'users': [{'id': client['id'], 'encryption': 'none', 'flow': 'xtls-rprx-vision'}]}]},
                           'streamSettings': {'network': 'tcp', 'security': 'reality', 'realitySettings': {
                               'serverName': state['server_name'], 'fingerprint': 'chrome',
                               'publicKey': state['public_key'], 'shortId': client['short_id']}}}]}


def uri(state, name, client, host, port):
    query = urlencode({'type': 'tcp', 'security': 'reality', 'flow': 'xtls-rprx-vision',
                       'sni': state['server_name'], 'fp': 'chrome', 'pbk': state['public_key'], 'sid': client['short_id']})
    return f'vless://{client["id"]}@{host}:{port}?{query}#{quote(name)}\n'


def new_client(state, name):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,47}', name) or name in state['clients']:
        raise ValueError('Use a new client name with 1-48 letters, digits, - or _')
    result = copy.deepcopy(state)
    client = {'id': str(uuid.uuid4()), 'short_id': secrets.token_hex(8)}
    result['clients'][name] = client
    files = {}
    endpoints = [('xray-client', state['endpoint'], state['port'])]
    if state.get('entry'):
        endpoints.append(('xray-client-via-entry', state['entry'], state['entry_port']))
    for stem, host, port in endpoints:
        files[stem + '.json'] = json.dumps(client_config(result, client, host, port), indent=2) + '\n'
        files[stem + '.txt'] = uri(result, name, client, host, port)
    return result, files
