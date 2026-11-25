"""Check pause and resume for two active peers sharing one outer IP in an isolated lab."""

import argparse
import contextlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tarfile
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import coldwire_access as panel
from convert_profile import awg_section, client_config, decode


def run(*args, **options):
    return subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options)


@contextlib.contextmanager
def tunnel(path, config, index):
    device = f'cwlab{index}'
    awg, daemon = path / 'awg', path / 'amneziawg-go'
    raw = '\n'.join(line for line in config['config'].splitlines()
                    if not line.startswith(('Address =', 'DNS =', 'MTU =')))
    raw = raw.replace('PersistentKeepalive = 25-35', 'PersistentKeepalive = 1')
    process = subprocess.Popen(['sudo', str(daemon), '-f', device], stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, env=dict(os.environ, GOMAXPROCS='1'))
    try:
        for _ in range(100):
            if Path(f'/run/amneziawg/{device}.sock').exists():
                break
            if process.poll() is not None:
                raise RuntimeError('Client tunnel exited')
            time.sleep(.1)
        else:
            raise RuntimeError('Client tunnel socket did not appear')
        run('sudo', str(awg), 'setconf', device, '/dev/stdin', input=raw + '\n', text=True)
        run('sudo', 'ip', 'address', 'add', config['client_ip'] + '/32', 'dev', device)
        run('sudo', 'ip', 'link', 'set', device, 'mtu', '1280', 'up')
        run('sudo', 'ip', 'route', 'add', '10.8.1.1/32', 'dev', device, 'metric', str(index))
        yield device
    finally:
        process.terminate()
        process.wait(timeout=15)


def reaches_exit(device, *, deadline=10):
    return subprocess.run(['ping', '-n', '-I', device, '-c', '1', '-W', str(deadline), '10.8.1.1'],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-test', required=True, action='store_true')
    parser.add_argument('--operator', required=True, type=Path)
    options = parser.parse_args()
    folder = options.operator.resolve()
    manifest = json.loads((folder / 'operator.json').read_text())
    if socket.gethostname() != 'kit-client' or [item['host'] for item in manifest['ssh']] != ['192.168.76.10', '192.168.76.20']:
        raise ValueError('Use the isolated COLDWIRE VM lab')

    def manage(action, name, routing=None):
        panel.manage(argparse.Namespace(folder=folder, action=action, name=name, user='lab-nat', routing=routing))

    def admit(conf):
        marker = conf['coldwireSpa']
        panel.admit(conf['hostName'], marker['port'], marker['key'])

    def wait_for_client(device, conf):
        start = time.monotonic()
        while time.monotonic() - start < 165:
            admit(conf)
            if reaches_exit(device, deadline=5):
                return round(time.monotonic() - start, 1)
        raise RuntimeError(f'{device} did not reestablish its session in 165 seconds')

    names = ('nat-guest-one', 'nat-guest-two')
    for name in names:
        manage('add', name, 'ru-services')
    try:
        configs = [client_config(awg_section(decode((folder / (name + '.vpn')).read_bytes()))) for name in names]
        for config in configs:
            admit(config)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with tarfile.open(panel.ROOT / 'dist/awg-native-linux-amd64.tar.gz') as bundle:
                for name in ('awg', 'amneziawg-go'):
                    binary = path / name
                    binary.write_bytes(bundle.extractfile(name).read())
                    binary.chmod(0o700)
            with tunnel(path, configs[0], 1) as first, tunnel(path, configs[1], 2) as second:
                assert reaches_exit(first) and reaches_exit(second), 'Both misconfigured profiles must be detected before pause'
                manage('pause', names[0])
                assert not reaches_exit(first, deadline=2) and reaches_exit(second), 'Pause affected a peer sharing the IP'
                print('PASS paused peer stopped while the second peer on the same IP kept working', flush=True)
                with panel.authorized(manifest, folder) as (_, exit_server):
                    assert exit_server.run('hostname').strip() == b'kit-exit'
                    expected_boot = exit_server.run('cat /proc/sys/kernel/random/boot_id').strip()
                    exit_server.run('systemd-run --on-active=2s --unit=cw-admin-peer-reboot /usr/bin/systemctl reboot')
                deadline = time.monotonic() + 180
                while time.monotonic() < deadline:
                    try:
                        with panel.authorized(manifest, folder) as (_, exit_server):
                            if exit_server.run('cat /proc/sys/kernel/random/boot_id').strip() != expected_boot:
                                exit_server.run('systemctl is-active awg-relay-kit-exit.service')
                                peers = set(exit_server.run(panel.NATIVE_AWG + ' show awg0 peers').decode().split())
                                assert configs[0]['client_pub_key'] not in peers and configs[1]['client_pub_key'] in peers
                                print('PASS AWG retained the unpaused peer and excluded the paused peer after B reboot', flush=True)
                                break
                    except panel.PANEL_ERRORS:
                        pass
                    time.sleep(4)
                else:
                    raise RuntimeError('Exit reboot was not observed')
                seconds = wait_for_client(second, configs[1])
                print(f'Active peer recovered {seconds}s after B and its SSH service were ready', flush=True)
                assert not reaches_exit(first, deadline=2), 'Paused peer regained access after reboot'
                manage('resume', names[0])
                seconds = wait_for_client(first, configs[0])
                assert reaches_exit(second), 'Resuming one peer interrupted the other'
                print(f'Resumed peer recovered in {seconds}s with its original profile', flush=True)
    finally:
        manage('revoke-user', 'lab-nat')
    print('PASS two active peers behind one source IP, pause, B reboot, resume, and revocation')


if __name__ == '__main__':
    main()
