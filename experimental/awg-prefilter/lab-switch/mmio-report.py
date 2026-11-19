# SPDX-License-Identifier: MIT
"""Match slow QEMU device accesses with BQL holds and Windows scheduler events."""
import argparse
import csv
import json
from pathlib import Path
import re
import runpy

bql = runpy.run_path(str(Path(__file__).with_name('bql-report.py')))


def waits(rows):
    """Return (switch-out, ready, switch-in, reason) for completed waits."""
    start = ready = None
    for tick, event, state, reason in sorted(rows):
        if event == 'O':
            start = (tick, reason) if state == 5 else None
            ready = None
        elif event == 'R' and start and ready is None:
            ready = tick
        elif event == 'I' and start:
            yield start[0], ready or tick, tick, start[1]
            start = None


def report(path, log, vcpu_tid):
    freq, first, last = bql['trace_extent'](path)
    ns = lambda tick: tick * 1_000_000_000 // freq
    ms = lambda duration: duration / 1_000_000
    main, holds = bql['qemu_log'](log)
    text = log.read_text(encoding='utf-8', errors='replace')
    identity = re.search(r'^CW47 main pid=(\d+) tid=\d+$', text, re.M)
    if not identity:
        raise ValueError('Missing QEMU process identity')
    pid = int(identity[1])

    rows, stacks, images, io = [], {}, {}, []
    with path.open(encoding='utf-8', newline='') as source:
        reader = csv.reader(source)
        next(reader)
        for row in reader:
            if row[0] == 'EXTENT':
                break
            if row[0] == 'IMAGE':
                base, size = int(row[1], 16), int(row[2], 16)
                if int(row[4]) in (0, 4, pid):
                    images[base] = (size, row[3])
                continue
            if int(row[2]) != vcpu_tid:
                continue
            tick, event = int(row[0]), row[1]
            if event in ('O', 'R', 'I'):
                rows.append((tick, event, int(row[4]), int(row[5])))
            elif event == 'S' and int(row[3]) == pid:
                stacks.setdefault(tick, []).extend(int(pc, 16) for pc in row[4:])
            elif event == 'H':
                io.append((ns(int(row[3])), ns(tick),
                           {'type': 'hard_fault', 'address': int(row[4], 16), 'bytes': int(row[6])}))
            elif event == 'D':
                io.append((ns(tick - int(row[4])), ns(tick),
                           {'type': 'disk_read' if row[3] == '10' else 'disk_write',
                            'disk': int(row[5]), 'bytes': int(row[6])}))
    if not rows or not stacks:
        raise ValueError('The ETW output is missing scheduler events or stacks for this vCPU')

    def module(address):
        for base, (size, name) in images.items():
            if base <= address < base + size:
                return {'image': name, 'rva': hex(address - base)}
        return {'address': hex(address)}

    states = bql['thread_spans']([(ns(tick), event, state) for tick, event, state, _ in rows])
    starts = [span[0] for span in states]
    waiting = list(waits(rows))
    results = []
    for line in text.splitlines():
        if not line.startswith('CW48 mmio '):
            continue
        access = {key: value.strip('"') for key, value in
                  re.findall(r'(\w+)=("[^"]*"|[^\s]+)', line)}
        if int(access['tid']) != vcpu_tid:
            continue
        request, prepared, done = (int(access[key]) for key in ('request', 'prepared', 'done'))
        if not ns(first) <= request <= prepared <= done <= ns(last):
            continue
        hold = next((row for row in holds if row['tid'] == vcpu_tid and
                     request <= row['acquired'] <= prepared <= done <= row['release']), None)
        low, high = (hold['acquired'], hold['release']) if hold else (prepared, done)
        if high - low < 1_000_000:
            continue
        record = {key: access[key] for key in ('addr', 'offset', 'width', 'dir', 'region', 'owner')}
        record.update(bql_logged=hold is not None, start_ns=low, end_ns=high,
                      duration_ms=ms(high - low), **bql['elapsed'](states, starts, low, high))
        record['main_bql_overlap_ms'] = max(
            (ms(min(high, row['acquired']) - max(low, row['request']))
             for row in holds if row['tid'] == main and row['request'] and
             max(low, row['request']) < min(high, row['acquired'])), default=0)
        record['waits'] = sorted(
            ({'overlap_ms': ms(min(high, ns(ready)) - max(low, ns(out))),
              'reason': reason, 'stack': [module(pc) for pc in stacks.get(resume, [])]}
             for out, ready, resume, reason in waiting if max(low, ns(out)) < min(high, ns(ready))),
            key=lambda wait: wait['overlap_ms'], reverse=True)
        record['disk_and_faults'] = [
            (entry | {'target': module(entry['address'])} if entry['type'] == 'hard_fault' else entry)
            | {'overlap_ms': ms(min(high, stop) - max(low, start))}
            for start, stop, entry in io if min(high, stop) - max(low, start) >= 500_000]
        results.append(record)
    return sorted(results, key=lambda access: access['duration_ms'], reverse=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('events', type=Path)
    parser.add_argument('qemu_log', type=Path)
    parser.add_argument('vcpu_tid', type=int)
    args = parser.parse_args()
    try:
        print(json.dumps(report(args.events, args.qemu_log, args.vcpu_tid), indent=2))
    except (OSError, IndexError, KeyError, ValueError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
