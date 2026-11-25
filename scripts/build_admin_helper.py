#!/usr/bin/env python3
"""Bundle the native desktop administration bridge with its offline resources."""

from argparse import ArgumentParser
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--spa-binary', type=Path, required=True)
    args = parser.parse_args()
    spa = args.spa_binary.resolve()
    if spa.name != 'coldwire-spa-linux-amd64' or spa.read_bytes()[:4] != b'\x7fELF':
        raise ValueError('Use the Linux amd64 SPA artifact named coldwire-spa-linux-amd64')

    with TemporaryDirectory() as work:
        command = [sys.executable, '-m', 'PyInstaller', '--onefile', '--name', 'coldwire-admin-helper',
                   '--distpath', str(args.output.resolve()), '--workpath', work, '--specpath', work]
        if sys.platform == 'darwin':
            command.extend(('--target-arch', 'universal2'))
            identity = os.environ.get('CODESIGN_SIGNATURE')
            if identity and identity != '-':
                command.extend(('--codesign-identity', identity))
        for name, destination in [
                ('servers', 'servers'),
                ('install_exit.py', '.'),
                ('exit_config.py', '.'),
                ('convert_profile.py', '.'),
                ('dist/awg-native-linux-amd64.tar.gz', 'dist'),
                ('dist/awg-native-linux-amd64.sha256', 'dist'),
                ('ru-direct.amnezia.json', '.'),
                ('ru-services.amnezia.json', '.'),
                (str(spa), 'dist')]:
            command.extend(('--add-data', f'{ROOT / name}:{destination}'))
        command.append('coldwire_admin_helper.py')
        subprocess.run(command, cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
