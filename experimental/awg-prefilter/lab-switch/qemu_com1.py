# SPDX-License-Identifier: MIT
"""Keep a lab VM's COM1 in memory and drain it after the measured interval."""
import argparse
import base64
import json
from pathlib import Path
import socket

DEVICE = 'lab-com1'
CAPACITY = 1024 * 1024


def with_ringbuf(argv):
    """Replace one explicit file-backed serial port, preserving other VM arguments."""
    args = list(argv)
    if args.count('-serial') != 1:
        raise ValueError('Expected exactly one -serial file:PATH argument')
    serial = args.index('-serial') + 1
    if serial == len(args) or not args[serial].startswith('file:'):
        raise ValueError('Expected exactly one -serial file:PATH argument')
    args[serial] = f'chardev:{DEVICE}'
    args.extend(('-chardev', f'ringbuf,id={DEVICE},size={CAPACITY}'))
    return args


def read_com1(port):
    """Drain the ring buffer using the local QMP monitor."""
    with socket.create_connection(('127.0.0.1', port), timeout=10) as conn, conn.makefile('rwb') as stream:
        def receive():
            line = stream.readline(2 * CAPACITY + 1)
            if not line.endswith(b'\n'):
                raise ValueError('Incomplete or oversized QMP message')
            message = json.loads(line)
            if not isinstance(message, dict):
                raise ValueError('Invalid QMP message')
            return message

        def request(command, arguments=None):
            message = {'execute': command}
            if arguments is not None:
                message['arguments'] = arguments
            stream.write(json.dumps(message).encode('ascii') + b'\r\n')
            stream.flush()
            while True:
                response = receive()
                if 'return' in response:
                    return response['return']
                if 'event' not in response:
                    raise ValueError(f'QMP {command}: {response.get("error", "unexpected reply")}')

        if 'QMP' not in receive():
            raise ValueError('No greeting from QMP')
        request('qmp_capabilities')
        data = request('ringbuf-read', {'device': DEVICE, 'size': CAPACITY, 'format': 'base64'})
        if not isinstance(data, str):
            raise ValueError('Expected base64 text from ringbuf-read')
        contents = base64.b64decode(data, validate=True)
        if len(contents) > CAPACITY:
            raise ValueError('QMP reply exceeds ring buffer capacity')
        return contents


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('port', type=int, help='Loopback QMP TCP port')
    parser.add_argument('output', type=Path, help='New local file for the COM1 log')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('QMP port must be in 1..65535')
    try:
        with args.output.open('xb') as out:
            try:
                data = read_com1(args.port)
                out.write(data)
            except (OSError, ValueError):
                out.close()
                args.output.unlink()
                raise
        print(f'Saved {len(data)} bytes from COM1')
    except (OSError, ValueError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
