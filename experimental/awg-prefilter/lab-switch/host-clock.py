"""Record Windows clock samples from a process separate from the QEMU lab."""
import argparse
import ctypes
import json
import os
import time
from ctypes import wintypes
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--seconds', type=int, default=900)
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('This observer runs on the Windows host')
    if args.seconds < 1:
        parser.error('--seconds must be positive')

    active_time = ctypes.WinDLL('kernel32', use_last_error=True).QueryUnbiasedInterruptTime
    active_time.argtypes = [ctypes.POINTER(ctypes.c_ulonglong)]
    active_time.restype = wintypes.BOOL
    ticks = ctypes.c_ulonglong()

    def sample():
        if not active_time(ctypes.byref(ticks)):
            raise ctypes.WinError(ctypes.get_last_error())
        return [time.perf_counter_ns(), time.time_ns(), ticks.value * 100]

    with args.output.open('x', encoding='utf-8') as output:
        samples = [sample()]
        deadline = samples[0][0] + args.seconds * 1_000_000_000
        try:
            while samples[-1][0] < deadline:
                time.sleep(0.05)
                samples.append(sample())
        except KeyboardInterrupt:
            pass
        json.dump({'columns': ['QPC_ns', 'wall_ns', 'active_Windows_ns'],
                   'samples': samples}, output, separators=(',', ':'))
        output.write('\n')
    print(f'Recorded {len(samples)} samples')


if __name__ == '__main__':
    main()
