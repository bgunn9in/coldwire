"""Export header keys and wire parameters from a disposable native AWG exit."""
import argparse
import base64
import ipaddress
import json
import os
from pathlib import Path
import re


def wire_parameters(parameters):
    values = {}
    ranges = []
    for i, size in enumerate((148, 92, 64, 32), 1):
        padding = parameters['S' + str(i)]
        if isinstance(padding, bool) or not re.fullmatch(r'[0-9]+', str(padding)):
            raise ValueError('Invalid AWG padding')
        padding = int(padding)
        if not 12 <= padding <= 65507 - size:
            raise ValueError('Header protection requires a usable IPv4 padding of at least 12')
        values['S' + str(i)] = str(padding)
        header = str(parameters['H' + str(i)])
        if not re.fullmatch(r'[0-9]+(?:-[0-9]+)?', header):
            raise ValueError('Invalid AWG header range')
        bounds = [int(n) for n in header.split('-')]
        low, high = bounds[0], bounds[-1]
        if not 0 <= low <= high <= 0xffffffff or any(low <= b and a <= high for a, b in ranges):
            raise ValueError('AWG header ranges must be valid and disjoint')
        ranges.append((low, high))
        values['H' + str(i)] = str(low) if low == high else f'{low}-{high}'
    trailers = str(parameters.get('RandomTrailers', 'off')).lower()
    if trailers not in ('true', 'false', 'on', 'off', '1', '0'):
        raise ValueError('Invalid RandomTrailers value')
    values['RandomTrailers'] = '1' if trailers in ('true', 'on', '1') else '0'
    return values


def export(state, output):
    address = ipaddress.IPv4Address(state['endpoint'])
    if not any(address in ipaddress.IPv4Network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')):
        raise ValueError('Disposable RFC1918 lab exit required')
    if state.get('installer') != 'awg-relay-kit-native-v1':
        raise ValueError('Native kit-managed lab exit required')
    parameters = state['parameters']
    wire = wire_parameters(parameters)
    values = [parameters['HeaderProtectionKey'], state['public_key']]
    for value in values:
        decoded = base64.b64decode(value, validate=True)
        if len(decoded) != 32 or decoded == bytes(32) or base64.b64encode(decoded).decode() != value:
            raise ValueError('Invalid or disabled lab key')
    contents = 'HeaderProtectionKey=' + values[0] + '\nServerPublicKey=' + values[1] + '\n'
    contents += ''.join(f'{key}={value}\n' for key, value in wire.items())
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
