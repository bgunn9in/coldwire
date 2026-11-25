#!/usr/bin/env python3
"""Stage the administration code and public server kit for an Android build."""

from argparse import ArgumentParser
from pathlib import Path
from shutil import copyfile


ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    'coldwire_admin_helper.py', 'coldwire_access.py', 'deploy.py', 'install_exit.py',
    'convert_profile.py', 'exit_config.py', 'exit_migration.py', 'legacy_profiles.py',
    'create_backup.py', 'restore_backup.py', 'update_lists.py',
)
DATA = (
    'ru-direct.amnezia.json', 'ru-services.amnezia.json',
    'dist/awg-native-linux-amd64.tar.gz', 'dist/awg-native-linux-amd64.sha256',
)
SERVER_FILES = (
    'backup-exit.sh', 'coldwire-access-firewall.service', 'coldwire-lockdown-ssh.service',
    'coldwire-lockdown.service', 'coldwire-spa.service', 'confirm-entry.sh', 'install-entry.sh',
    'install-exit.sh', 'lockdown_rules.py', 'migrate-native-exit.py', 'native-runtime.py',
    'preflight-host.sh', 'probe-relay.py', 'restore-exit.sh', 'rollback-entry.sh',
    'spa_access.py', 'stage-access.sh', 'stage-lockdown.sh',
)


def stage(output, spa):
    with spa.open('rb') as binary:
        header = binary.read(20)
    if spa.name != 'coldwire-spa-linux-amd64' or header[:6] != b'\x7fELF\x02\x01' or header[18:20] != b'\x3e\x00':
        raise ValueError('Use the Linux amd64 SPA executable built from servers/spa')
    package = output / 'coldwire_admin_bundle'
    package.mkdir(parents=True)
    for name in (*MODULES, *DATA, *(f'servers/{name}' for name in SERVER_FILES)):
        source = ROOT / name
        destination = package / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        copyfile(source, destination)
    copyfile(spa, package / 'dist' / spa.name)
    (package / '__init__.py').write_text(
        'import logging\n'
        'import sys\n'
        'from pathlib import Path\n\n'
        'ssh_log = logging.getLogger("paramiko")\n'
        'ssh_log.addHandler(logging.NullHandler())\n'
        'ssh_log.propagate = False\n\n'
        'path = str(Path(__file__).resolve().parent)\n'
        'sys.path.insert(0, path)\n'
        'try:\n'
        '    from coldwire_admin_helper import invoke\n'
        'finally:\n'
        '    sys.path.remove(path)\n',
        encoding='utf-8',
    )


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--spa-binary', type=Path, required=True)
    args = parser.parse_args()
    stage(args.output, args.spa_binary)


if __name__ == '__main__':
    main()
