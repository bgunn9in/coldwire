"""Verify the source seen by HTTP destinations through the isolated COLDWIRE relay."""

import argparse
from ipaddress import IPv4Address, IPv4Network
import json
from pathlib import Path
import socket
import tarfile
import tempfile
import time
from unittest.mock import patch
from urllib.request import ProxyHandler, build_opener

from smoke_client_admin_nat_vm import panel, run, tunnel
from convert_profile import awg_section, client_config, decode


ENTRY, EXIT, PROVIDER = '192.168.76.10', '192.168.76.20', '192.168.76.30'
TARGETS = ('198.51.100.17', '203.0.113.17')
OBSERVER = '''from http.server import BaseHTTPRequestHandler, HTTPServer
class SourceHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(self.client_address[0].encode())
HTTPServer(("0.0.0.0", 18080), SourceHandler).serve_forever()
'''


def read_sources():
    opener = build_opener(ProxyHandler({}))
    result = []
    for address in TARGETS:
        for attempt in range(12):
            try:
                with opener.open(f'http://{address}:18080/', timeout=3) as response:
                    result.append(str(IPv4Address(response.read(32).decode())))
                break
            except OSError:
                if attempt == 11:
                    raise
                time.sleep(.5)
    return tuple(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-test', required=True, action='store_true')
    parser.add_argument('--operator', type=Path, required=True)
    folder = parser.parse_args().operator.resolve()
    manifest = json.loads((folder / 'operator.json').read_text())
    if socket.gethostname() != 'kit-client' or [item['host'] for item in manifest['ssh']] != [ENTRY, EXIT]:
        raise ValueError('Use the isolated COLDWIRE VM lab')

    def manage(action, name, routing=None):
        panel.manage(argparse.Namespace(folder=folder, action=action, name=name, user='lab-routes', routing=routing))
    destinations = '{ ' + ', '.join(TARGETS) + ' }'
    with panel.authorized(manifest, folder) as (a, b):
        assert a.run('hostname').strip() == b'kit-entry' and b.run('hostname').strip() == b'kit-exit'
        panel.put(a, '/run/cw-source-observer.py', OBSERVER)
        a.run('''
ip address add 198.51.100.17/32 dev lo
ip address add 203.0.113.17/32 dev lo
systemd-run --unit=cw-source-observer /usr/bin/python3 /run/cw-source-observer.py
''' + f"nft 'insert rule inet coldwire_lockdown wan ip saddr {{ {PROVIDER}, {EXIT} }} "
              f"ip daddr {destinations} tcp dport 18080 accept'")
        b.run(f'''
ip route add {TARGETS[0]}/32 via {ENTRY} src {EXIT}
ip route add {TARGETS[1]}/32 via {ENTRY} src {EXIT}
nft 'insert rule ip awg_exit forward iifname "awg0" ip daddr {destinations} tcp dport 18080 accept'
nft 'insert rule ip awg_exit forward oifname "awg0" ip saddr {destinations} ct state established accept'
nft 'insert rule ip awg_exit postrouting ip saddr 10.8.1.0/24 ip daddr {destinations} tcp dport 18080 snat to {EXIT}'
''')

    names = {'lab-routes-all': 'all', 'lab-routes-services': 'ru-services', 'lab-routes-direct': 'ru-direct'}
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory)
        with tarfile.open(panel.ROOT / 'dist/awg-native-linux-amd64.tar.gz') as archive:
            for filename in ('awg', 'amneziawg-go'):
                tool = path / filename
                tool.write_bytes(archive.extractfile(filename).read())
                tool.chmod(0o700)
        (path / 'ru-services.amnezia.json').write_text('[{"ip":"198.51.100.0/24"}]')
        (path / 'ru-direct.amnezia.json').write_text('[{"ip":"198.51.100.0/23"}]')
        try:
            for target in TARGETS:
                run('sudo', 'ip', 'route', 'replace', target + '/32', 'via', ENTRY, 'src', PROVIDER)
            assert read_sources() == (PROVIDER, PROVIDER), 'The observer must see the direct source before VPN'
            for index, (name, mode) in enumerate(names.items(), 1):
                with patch.object(panel, 'ROOT', path):
                    manage('add', name, mode)
                profile = decode((folder / (name + '.vpn')).read_bytes())
                assert profile['coldwireRouting']['mode'] == mode
                exclusions = [IPv4Network(cidr) for cidr in profile['coldwireRouting']['ipv4']]
                config = client_config(awg_section(profile))
                marker = config['coldwireSpa']
                panel.admit(ENTRY, marker['port'], marker['key'])
                with tunnel(path, config, index) as device:
                    for target in TARGETS:
                        if any(IPv4Address(target) in prefix for prefix in exclusions):
                            run('sudo', 'ip', 'route', 'replace', target + '/32', 'via', ENTRY, 'src', PROVIDER)
                        else:
                            run('sudo', 'ip', 'route', 'replace', target + '/32', 'dev', device)
                    sources = read_sources()
                    expected = (EXIT, EXIT) if mode == 'all' else (PROVIDER, EXIT)
                    assert sources == expected, (mode, sources, expected)
                    print(f'PASS {mode}: observer saw {sources}', flush=True)
        finally:
            if any(name in panel.load_devices(folder / 'devices.json') for name in names):
                manage('revoke-user', 'lab-routes')


if __name__ == '__main__':
    main()
