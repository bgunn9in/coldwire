import argparse
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import time

def main():
    if os.name != 'nt':
        raise SystemExit('This checks a Windows lab helper')
    parser = argparse.ArgumentParser()
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--workdir', required=True, type=Path)
    args = parser.parse_args()
    binary = args.binary.resolve(strict=True)
    workdir = args.workdir.resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    stats_path = workdir / 'switch-stats.json'
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 62591))
    subprocess.run([str(binary), '--self-test'], check=True)
    process = subprocess.Popen([str(binary), '62591', str(stats_path)], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
    clients = []


    def connect():
        value = socket.create_connection(('127.0.0.1', 62591), timeout=3)
        clients.append(value)
        return value


    def receive(client, size):
        result = bytearray()
        while len(result) < size:
            value = client.recv(size-len(result))
            assert value, 'Premature switch disconnect'
            result.extend(value)
        return bytes(result)


    def frame(destination, source, payload, protocol=b'\x08\x00'):
        value = destination + source + protocol + payload
        return struct.pack('!I', len(value)) + value


    try:
        assert process.stdout.readline().strip() == b'ready'
        a, b, d = connect(), connect(), connect()
        ma, mb, md = (bytes.fromhex(v) for v in ('52540058000a', '52540058000b', '52540058000d'))
        broadcast = frame(b'\xff'*6, mb, b'x'*20)
        b.sendall(broadcast)
        assert receive(a, len(broadcast)) == broadcast
        assert receive(d, len(broadcast)) == broadcast
        first, second = frame(mb, ma, b'a'*200), frame(mb, ma, b'z'*300)
        a.sendall(first[:3]); time.sleep(.02); a.sendall(first[3:]+second)
        assert receive(b, len(first+second)) == first+second
        d.settimeout(.1)
        try:
            d.recv(1)
            raise AssertionError('Learned unicast reached unrelated port')
        except socket.timeout:
            pass
        d.settimeout(3)
        fourth, fifth = connect(), connect()
        try:
            assert fifth.recv(1) == b''
        except ConnectionResetError:
            pass
        fourth.close(); time.sleep(.05)
        opaque = frame(mb, ma, b'opaque IPv6 data'*12, b'\x86\xdd')
        a.sendall(opaque)
        assert receive(b, len(opaque)) == opaque
        maximum = frame(mb, ma, b'm'*(65536-14))
        a.sendall(maximum)
        assert receive(b, len(maximum)) == maximum
        batch = b''.join(frame(mb, ma, bytes([i])*60000) for i in range(18))
        for _ in range(6):
            a.sendall(batch)
            assert receive(b, len(batch)) == batch
        noise = bytearray(284)
        noise[0], noise[9] = 0x45, 17
        noise[12:20] = bytes([192, 168, 76, 40, 192, 168, 76, 10])
        for source_port in (46000, 40000, 40063, 40064, 65535):
            noise[20:26] = struct.pack('!HHH', source_port, 32497, 264)
            packet = frame(mb, md, noise)
            d.sendall(packet)
            assert receive(b, len(packet)) == packet
        noise[23] ^= 1
        unrelated = frame(mb, md, noise)
        d.sendall(unrelated)
        assert receive(b, len(unrelated)) == unrelated
        a.sendall(struct.pack('!I', 65537)); time.sleep(.05)
        try:
            assert a.recv(1) == b''
        except ConnectionResetError:
            pass  # Windows may reset an intentionally closed malformed stream.
        d.sendall(packet)
        assert receive(b, len(packet)) == packet
        stamp = time.monotonic_ns()
        for _ in range(40):
            stats = json.loads(stats_path.read_text())
            if stats['snapshot_ns'] >= stamp:
                break
            time.sleep(.05)
        else:
            raise AssertionError('Stale native-switch statistics')
        assert stats['noise_frames'] == 6 and sum(stats['noise_bins_100ms'].values()) == 6
        assert stats['dropped'] == 0 and stats['malformed_connections'] == 1
        assert stats['rejected_connections'] == 1 and stats['tcp_nodelay']
        print('PASS TCP framing, maximum length, ring wrap/order, unicast, opaque payload, peer cap and exact counter')
    finally:
        for client in clients:
            client.close()
        process.terminate(); process.wait(timeout=3)
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 62591))


if __name__ == '__main__':
    main()
