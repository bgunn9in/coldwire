# Native lab switch and verified 25,000 packets/s

English | [Русский](validation-v9.ru.md)

Test date: 12 November 2026. The C/Winsock switch sustained the requested
25,000 noise packets/s with useful TCP traffic. All six primary filtered
runs delivered about 100 Mbit/s and stayed below 75% CPU on every guest.
Ordinary DNAT saturated entry and failed both the CPU and throughput targets.

The [JSON](results-v9.json) records fourteen trials: three clean controls,
two pilots and nine primary comparisons. All eleven noisy trials passed
the rate check. Independent counters saw all 3,300,000 noise packets;
all 1400 timed pings returned. The ordinary filter binaries, crypto checks
and production installers are unchanged.

## The replacement switch

The new [source](lab-switch/native-switch.c), [tests](lab-switch/test_switch.py)
and [build instructions](lab-switch/README.md) are included in the repository.
It replaces the Python host relay from [v8](validation-v8.md), retaining
QEMU's TCP frame format, MAC learning, FIFO forwarding, a 4-MiB output
limit per peer and independent arrival counters. It accepts four peers
on localhost, enables `TCP_NODELAY` and uses bounded buffers and telemetry.
It creates no host adapters and changes no routes or firewall settings.

The helper runs on Windows, outside the four guest memory budgets.
It is not deployed by the VPS installers and performs no VPN authentication
or decryption. The server-side protocol remains AWG 3.1.

The optimized MinGW-w64 build passed warnings as errors, queue-wrap/bounds
and MAC-table/frame-parser checks. Socket tests checked split/coalesced reads, exact
frame order, a maximum-length frame, opaque payloads, learned unicast,
connection limits, malformed-frame disconnection and exact noise counting.
More than 6 MiB crossed the output ring during the functional test without
loss or byte changes. The standalone Python test imports without starting
a listener or parsing command-line arguments during test discovery.

## VM and traffic settings

Four fresh copy-on-write guests each had 1 vCPU and 1024 MiB RAM. They used
the same Debian 13 disks, patched QEMU/WHPX build and ordinary filter binaries
as the preceding study. A/B/C used Linux 6.12.116; D used 6.12.115. SHA-256
values, compiler version and guest resources are recorded in the JSON.
No CPU quota or host affinity setting was applied.

C requested 100 Mbit/s TCP upload, with a 5% acceptance tolerance, for eight
measured seconds after one second of warmup. D targeted twelve seconds
at 25,000 UDP packets/s, using one flow, a random 256-byte payload reused
within each trial and offered bursts of up to 4096 packets. Noise began
about a second before the CPU window. Source burst traces and independent
switch arrival bins were retained. Offered burst size does not imply an
instantaneous burst at the entry; pacing and virtual I/O still affect timing.

`baseline` uses the ordinary grouped filter and unchanged kernel guard:
50,000 packets/s with a 5000-packet aggregate burst, and 35,000 packets/s
with a 3500-packet source-IP/UDP-port burst. `ifb1024` adds the previous
200-Mbit/s TBF with a 64-KiB burst and 1-MiB limit. DNAT uses none of these
experimental admission components. No trusted-IP cache was introduced.

The resident collector and fixed workload launcher from v8 remained in use.
They avoid new SSH authentication and sudo inside the measurement window.
Their overhead stays in whole-guest CPU. Sampling used nominal 250-ms
intervals; actual analyzed durations were 236.34 to 263.07 ms.
Only complete intervals between the before/after marks were selected,
covering TCP warmup/run and the two-second tail. Sliding four-sample windows
sum CPU ticks. Busy CPU includes user, nice, system, IRQ and softirq; idle,
iowait and steal remain in the denominator. A sample strictly above 75%
fails at that resolution. This does not establish an instantaneous ceiling.

## Primary comparison

Three repeats per policy used rotated/reversed order. All nine met the
sender-rate and delivery checks. Table CPU values are maxima over the
nominal 250-ms samples, including measurement overhead. Passing requires
the offered rate, useful throughput and CPU criterion on all four guests.

| Policy | Median Mbit/s | A max CPU % | B max CPU % | C max CPU % | D max CPU % | Passed |
|---|---:|---:|---:|---:|---:|---:|
| dnat | 66.40 | 100.00 | 65.38 | 100.00 | 18.52 | 0/3 |
| baseline | 100.07 | 55.17 | 42.86 | 22.22 | 17.39 | 3/3 |
| ifb1024 | 100.09 | 62.96 | 44.00 | 28.00 | 34.78 | 3/3 |

The six filtered cases also stayed below 75% in every four-sample window.
They had no NFQUEUE, netlink-user, shaper, kernel-guard or virtual-switch
drops. All post-guard packets were accounted for. DNAT delivered 60.08 to
67.75 Mbit/s and saturated entry in every repeat; one repeat also had a hot
client sample. These failures are retained. All three clean controls had
about 100 Mbit/s, no losses and no guest CPU violation.

The filtered pilot likewise passed. The DNAT pilot offered the correct
noise rate but delivered 58.64 Mbit/s with entry at 100% CPU. Pilots are
separate from the primary table.

## What the faster backend establishes

The source and independent arrival counters now verify the requested
25,000-packet/s workload. Recorded source means were 24,999.65 to
24,999.80 packets/s; host first-to-last means were 25,010 to 25,021,
excluding the final pacing sleep. The earlier Python backend did not sustain that
request in v8. Native-switch process CPU in the primary runs was about
82 to 85% of one Windows logical CPU with filtering and about 89 to 91%
with DNAT. These host process percentages have a different reference from
whole-guest CPU; the user's 75% acceptance criterion applies to each VM.
The host has 32 logical CPUs, and the native helper was not CPU-capped.

The new backend therefore resolves the tested pacing limitation, with
limited headroom on its own core. This study establishes neither a maximum
switch rate nor maximum filter capacity. The backend also changes arrival
timing. Absolute CPU or throughput differences from earlier studies must
not be attributed solely to packet-processing code, which was unchanged.
Zero switch drops or blocked sends do not measure every queue inside QEMU.

## Decision and remaining scope

Keep the native switch for this local lab and retain the grouped filter
without IFB as the simpler candidate for further research. It met the
tested CPU budget at the verified offered rate without weakening checks.
IFB also passed this series, but earlier useful-packet losses and the
fragment-selector gap remain unresolved, so it stays outside default setup.

The noise was invalid random UDP. This does not benchmark MAC1-valid
handshake floods or traffic reusing captured transport prefixes. HPK/MAC1
still provides partial filtering, without proving client identity. No new
physical GUI-client, real-VPS, DPI or maximum-flood test was performed.
The unchanged filter's protocol/sanitizer suites were not rerun; the new
switch received its own build, unit and socket tests.

Rollback restored ordinary DNAT and both native clients passed their probes.
Original filter/source and personal JSON hashes were unchanged. All four
VMs, the switch and seed helper were stopped; all lab/self-test ports were
released. Live servers and the user's VPN were untouched. English and Russian reports were reviewed with Humanizer.
