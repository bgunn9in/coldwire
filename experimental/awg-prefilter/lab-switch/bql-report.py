# SPDX-License-Identifier: MIT
"""Correlate Windows QEMU BQL timestamps with selected ETW scheduler events."""
import argparse
from bisect import bisect_right
from collections import defaultdict
import csv
import json
from pathlib import Path
import re


def qemu_log(path):
    main = []
    holds = []
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        fields = dict(re.findall(r'(\w+)=([^\s]+)', line))
        if line.startswith('CW47 main '):
            main.append(int(fields['tid']))
        elif line.startswith('CW47 bql '):
            hold = {key: int(fields[key]) for key in
                    ('tid', 'request', 'acquired', 'release', 'previous_owner', 'line')}
            hold['source'] = Path(fields['file']).name
            holds.append(hold)
    if len(main) != 1:
        raise ValueError('Expected one CW47 main marker in this QEMU log')
    return main[0], holds


def trace_extent(path):
    with path.open('rb') as source:
        header = source.readline().decode('ascii').strip().split(',')
        source.seek(max(0, path.stat().st_size - 256))
        footer = source.read().splitlines()[-1].decode('ascii').split(',')
    if len(header) != 2 or header[0] != 'FREQ' or len(footer) != 4 or footer[0] != 'EXTENT':
        raise ValueError('Expected complete scheduler-read output')
    frequency = int(header[1])
    first, last, lost = map(int, footer[1:])
    if frequency <= 0 or not 0 < first < last or lost:
        raise ValueError('Invalid scheduler clock or trace with lost events')
    return frequency, first, last


def thread_spans(rows):
    spans = []
    start = None
    state = 'unknown'
    for timestamp, event, old_state in sorted(rows, key=lambda row: row[0]):
        if event == 'R' and state in ('running', 'ready'):
            continue
        if start is not None and start < timestamp:
            spans.append((start, timestamp, state))
        start = timestamp
        if event == 'I':
            state = 'running'
        elif event == 'R' or old_state in (1, 3, 7):
            state = 'ready'
        elif event == 'O' and old_state == 5:
            state = 'waiting'
        else:
            state = 'unknown'
    return spans


def elapsed(spans, entries, low, high):
    counts = dict(running=0, ready=0, waiting=0, unknown=0)
    index = max(0, bisect_right(entries, low) - 1)
    while index < len(spans) and spans[index][0] < high:
        start, end, state = spans[index]
        counts[state] += max(0, min(end, high) - max(start, low))
        index += 1
    counts['unknown'] += high - low - sum(counts.values())
    return {name + '_ms': value / 1_000_000 for name, value in counts.items()}


def report(args, main_tid, holds):
    frequency, first, last = trace_extent(args.events)

    def ns(tick):
        return tick * 1_000_000_000 // frequency

    start = ns(first) if args.start_ns is None else args.start_ns
    end = ns(last) if args.end_ns is None else args.end_ns
    if not ns(first) <= start < end <= ns(last):
        raise ValueError('The requested time window must fit inside the ETW capture')
    requests = sorted((row for row in holds if row['tid'] == main_tid and
                       start <= row['request'] <= row['acquired'] <= end and
                       row['acquired'] - row['request'] >= 5_000_000),
                      key=lambda row: row['acquired'] - row['request'], reverse=True)
    result = {'main_tid': main_tid, 'start_qpc_ns': start, 'end_qpc_ns': end,
              'main_acquires_at_least_5ms': len(requests), 'acquisitions': []}
    if not requests:
        with args.events.open(encoding='ascii', newline='') as source:
            if not any(len(row) == 6 and int(row[2]) == main_tid for row in csv.reader(source)):
                raise ValueError('The scheduler output has no events for the QEMU main thread')
        return result

    relevant = {main_tid} | {hold['tid'] for hold in holds}
    events = defaultdict(list)
    with args.events.open(encoding='ascii', newline='') as source:
        reader = csv.reader(source)
        next(reader)
        for row in reader:
            if row[0] == 'EXTENT':
                break
            tick, event, tid, _cpu, state, _reason = row
            if int(tid) in relevant:
                events[int(tid)].append((ns(int(tick)), event, int(state)))
    if main_tid not in events:
        raise ValueError('The scheduler output has no events for the QEMU main thread')
    spans = {tid: thread_spans(rows) for tid, rows in events.items()}
    starts = {tid: [row[0] for row in rows] for tid, rows in spans.items()}

    def timing(tid, low, high):
        return elapsed(spans.get(tid, ()), starts.get(tid, ()), low, high)

    for request in requests:
        low, high = request['request'], request['acquired']
        owners = []
        for hold in holds:
            if hold['tid'] == main_tid:
                continue
            begin, finish = max(low, hold['acquired']), min(high, hold['release'])
            if begin < finish:
                owners.append({'tid': hold['tid'], 'is_vcpu': hold['tid'] == args.vcpu_tid,
                               'source': hold['source'], 'line': hold['line'],
                               'overlap_ms': (finish - begin) / 1_000_000,
                               **timing(hold['tid'], begin, finish)})
        owners.sort(key=lambda owner: owner['overlap_ms'], reverse=True)
        result['acquisitions'].append({
            'request_qpc_ns': low, 'acquired_qpc_ns': high, 'elapsed_ms': (high - low) / 1_000_000,
            'owner_tid_sample': request['previous_owner'], **timing(main_tid, low, high),
            'overlapping_holders': owners,
        })
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest='mode', required=True)
    threads = modes.add_parser('threads', help='Print the thread IDs to pass to scheduler-read')
    threads.add_argument('qemu_log', type=Path)
    analyze = modes.add_parser('report', help='Summarize captured BQL acquisitions of at least 5 ms')
    analyze.add_argument('events', type=Path)
    analyze.add_argument('qemu_log', type=Path)
    analyze.add_argument('--vcpu-tid', type=int)
    analyze.add_argument('--start-ns', type=int, help='Start of the analysis window in QPC nanoseconds')
    analyze.add_argument('--end-ns', type=int, help='End of the analysis window in QPC nanoseconds')
    args = parser.parse_args()
    try:
        tid, holds = qemu_log(args.qemu_log)
        if args.mode == 'threads':
            for ident in sorted({tid} | {row[k] for row in holds
                                         for k in ('tid', 'previous_owner') if row[k]}):
                print(ident)
        else:
            print(json.dumps(report(args, tid, holds), indent=2))
    except (OSError, IndexError, KeyError, ValueError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
