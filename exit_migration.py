"""Stage a guarded cutover of the Docker-based AmneziaWG exit."""

import json

from convert_profile import awg_section, client_config, decode
from deploy import ROOT
from exit_config import valid_key
from install_exit import BIN, BUNDLE, read_bundle, service_text
from legacy_profiles import AWG as DOCKER_AWG


DEST = '/var/lib/coldwire-native-exit'
DRIVER = f'python3 {DEST}/driver.py'
NATIVE_EXIT = {'awg': DEST + '/bin/awg', 'config': DEST + '/native.awg'}


def state(node):
    return node.run(f'if test -f {DEST}/driver.py; then {DRIVER} status; else echo docker; fi').decode().strip()


def stage(entry, node, folder, timeout, put):
    if state(node) not in {'docker', 'docker-restored'}:
        raise ValueError('A migration is already pending or confirmed. Run status first.')
    if not (folder / 'legacy-template.vpn').is_file():
        raise ValueError('The operator folder needs a working guest export named legacy-template.vpn')
    original = decode((folder / 'legacy-template.vpn').read_bytes())
    if {'userName', 'password', 'sshKey'} & original.keys():
        raise ValueError('The template must be a guest export')
    profile = client_config(awg_section(original))
    configured = valid_key(profile['server_pub_key'])
    running = node.run(DOCKER_AWG + ' show awg0 public-key').decode().strip()
    if configured != running:
        raise ValueError('The guest template is for a different AmneziaWG server')
    files = read_bundle(BUNDLE)
    node.run(f'''
test ! -L {DEST}
test ! -L {DEST}/bin
command -v iptables >/dev/null
install -d -m 700 {DEST} {DEST}/bin
''')
    for binary in ('awg', 'amneziawg-go'):
        put(node, f'{DEST}/bin/{binary}', files[binary], 0o700)
    put(node, f'{DEST}/driver.py', (ROOT / 'servers/migrate-native-exit.py').read_bytes().replace(b'\r\n', b'\n'), 0o700)
    settings = node.run(f'{DRIVER} stage {entry}', timeout=75).decode()
    port = json.loads(settings)['published']
    unit = service_text(port).replace(f'{BIN}/native-runtime.py', f'{DEST}/driver.py').replace(str(BIN), DEST + '/bin')
    unit = unit.replace('[Unit]\n', '[Unit]\nRequires=coldwire-lockdown.service\nAfter=coldwire-lockdown.service\n')
    unit = unit.replace('ReadWritePaths=/run/amneziawg', 'ReadWritePaths=/run/amneziawg /run/xtables.lock')
    put(node, f'{DEST}/native.service', unit, 0o600)
    node.run(f'{DRIVER} cutover {timeout}', timeout=140)
    print(f'B switched to native AmneziaWG. The rollback timer is armed for {timeout} seconds.')
    print('Check SSH through A and test an existing VPN profile before confirming.')
