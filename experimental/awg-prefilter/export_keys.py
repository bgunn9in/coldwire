"""Export only the two prefilter inputs from a disposable native AWG lab exit."""
import argparse
import base64
import ipaddress
import json
import os
from pathlib import Path


def export(state, output):
    address = ipaddress.IPv4Address(state['endpoint'])
    if not any(address in ipaddress.IPv4Network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')):
        raise ValueError('Disposable RFC1918 lab exit required')
    if state.get('installer') != 'awg-relay-kit-native-v1':
        raise ValueError('Native kit-managed lab exit required')
    parameters = state['parameters']
    if any(str(parameters['S' + str(i)]) != '12' or str(parameters['H' + str(i)]) != str(i) for i in range(1, 5)):
        raise ValueError('Prototype requires S1-S4=12 and H1-H4=1,2,3,4')
    values = [parameters['HeaderProtectionKey'], state['public_key']]
    for value in values:
        decoded = base64.b64decode(value, validate=True)
        if len(decoded) != 32 or decoded == bytes(32) or base64.b64encode(decoded).decode() != value:
            raise ValueError('Invalid or disabled lab key')
    contents = 'HeaderProtectionKey=' + values[0] + '\nServerPublicKey=' + values[1] + '\n'
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(contents)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vm-test', action='store_true', required=True)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    export(json.loads(args.state.read_text()), args.output)
