# Admission burst 2048 under multi-IP noise

English | [Русский](validation-v28.ru.md)

Measurements in UTC: 2026-11-15.
With a 2048-packet burst, the four-IP upload case lost 1170
of 360,002 useful UDP datagrams; the sixteen-IP case lost
1372 of 360,001. The single-IP success in
[v27](validation-v27.md) does not establish loss-free service under multi-IP noise.
The public default remains 1024. See [data](results-v28.json).

## Workload and checks

Eight completed cases compare bursts 1024/2048 for 4/16 noise IPv4 sources
and both useful traffic directions. Four fresh Debian 13 guests ran kernel
6.12.116 under QEMU 11.1.3/WHPX, each with one vCPU and 1024 MiB. No CPU quota
or pass/fail threshold was applied. The AWG filter, v27 recovery binary, native
clients, profiles, keys and ports are unchanged. Their source/binary hashes are
recorded; Go was not rebuilt and its unchanged tests were not rerun.

Noise is 25,000 datagrams/s in total for 70 seconds, across 64 UDP sockets,
with the same 256-byte captured-prefix fixture and unusable transport body.
Four sources have 16 sockets each; sixteen sources have four. The generator
binds real address aliases on its own disposable guest, starting at
`192.168.76.40`. It uses one NIC/MAC and the same shared 4096-packet burst
schedule. This tests source cardinality; independent hosts, independent burst
phases, source spoofing and address churn are outside this acquisition.

The sender reports successful sends per IP. The Windows switch independently
counts the matching frames per IP. Counts agree exactly: 1,750,000 noise
datagrams in each case, 14,000,000 overall. Sender and
Linux ingress rates meet the existing 1% tolerance. The switch retains four
connected ports and zero drop delta in every case.

Useful UDP requests 6000 datagrams/s with 128-byte payloads for 60 seconds.
Complete inner captures count unique sequence numbers, including GSO/GRO;
iperf loss estimates are separate. The gateway changes one client's IP and
NAT port three times, 250 ms after each prior conntrack deletion finishes.
A second native profile stays put. Each profile sends 100 ordinary probes
at 500-ms intervals; the moving profile also sends 100 probes at 50-ms intervals.
Their deadline is still one second. Captures verify late RTT on the client's
own clock and distinguish missing requests from lost return traffic.

Netem applies half of RTT 300 ms in each A-B direction, with 30-ms jitter per
direction, including the control channel. Each queue holds up to 16,384 packets;
no random loss is configured. Twenty physical pings verify each setup. Paired
cases use the same seed and workload, with AB/BA order varied. Scheduling and
batching can still change effective delay draws; these are individual pairs,
not a statistical latency or throughput guarantee.

The live nftables aggregate rate and burst are checked before each load:
6000/s with burst 1024 or 2048. The per-source limit stays 1500/s with burst 4096;
recovery spacing/cache/expiry budgets are those of v27. The lab's counters now
cover all sixteen noise addresses. The switch adds sixteen bounded counters;
its forwarding, queues and TCP handling are unchanged. Switch framing/bounds,
source-range exclusions, Linux sender allocation and resident argument tests
passed before traffic. The sender was compiled with the entry guest's existing
GCC and copied to the generator; there was no package install or compilation
during measurement.

## Results

Upload means client to exit; download means exit to client. CPU peaks cover
all nominal 250-ms guest samples. Weighted means and all samples are in the
data. Upload uses the existing outer capture setup; its cost differs from
the leaner download captures.

| Noise IPs | Aggregate burst | Direction | UDP sent / missing | Early client drops | Frequent on time / late / missing | Entry CPU peak % | Exit CPU peak % |
|---|---|---|---|---|---|---|---|
| 4 | 1024 | upload | 360002 / 1446 | 1451 | 97 / 0 / 3 | 64.00 | 48.00 |
| 4 | 2048 | upload | 360002 / 1170 | 1174 | 96 / 0 / 4 | 53.85 | 57.69 |
| 16 | 2048 | upload | 360001 / 1372 | 1377 | 95 / 0 / 5 | 45.83 | 48.28 |
| 16 | 1024 | upload | 360001 / 1452 | 1458 | 95 / 0 / 5 | 48.00 | 51.72 |
| 4 | 2048 | download | 362082 / 0 | 0 | 94 / 6 / 0 | 60.00 | 92.59 |
| 4 | 1024 | download | 362339 / 0 | 1 | 93 / 6 / 1 | 51.85 | 84.00 |
| 16 | 1024 | download | 362477 / 0 | 3 | 92 / 6 / 2 | 52.00 | 80.00 |
| 16 | 2048 | download | 362101 / 0 | 2 | 90 / 8 / 2 | 53.85 | 82.76 |

Across the four 2048-burst cases, upload captures count
720,003 source datagrams and
2542 missing; download counts
724,183 and 0 missing.
Frequent probes returned 375/400 on time, 14 late,
and 11 were absent from client captures. Ordinary probe
results and missing sequence ranges are retained per case.

Whole-study guest CPU peaks were entry 64.00%, exit
92.59%, client 91.30% and noise generator
24.00%. Exit AWG peak RSS was 79.76 MiB with the same
96-MiB Go soft limit. This is not a maximum-throughput or memory-exhaustion test.

No noise source obtained a verified lease or entered the trusted path. Queue,
capture, interface and network error counters remain available in the data;
early admission drops are measured outcomes and are not discarded as bad runs.

## Why burst capacity is insufficient

Four source limits of 1500/s can already reach the entire 6000/s aggregate
unknown-traffic allowance. A roaming client's new tuple shares that allowance
until B's authenticated proof reaches A. Raising the burst stores more short
term credit; it reserves no sustained rate or priority for the new client.
The observed upload gaps and early-guard counters occur during discovery.
Reverse ciphertext recovery cannot replace requests or UDP datagrams dropped
on this forward path. Return-path timing has its separate WAN/recovery limits.

Do not promote 2048 to the default based on v27. It did not remove the multi-IP
admission losses in these tests. Protecting fresh client traffic under a saturated
unknown allowance needs a separately tested admission policy; it cannot assume
a permanent client IP. No rate, security condition or production configuration
was relaxed to turn these results into a pass.

Before shutdown, stock exit binary/unit/environment, ordinary DNAT and original
client NAT/profiles were restored and both probes passed. The extra noise
aliases and sender files were removed; original observation helpers/rules were
restored. All four guests and owned seed/switch helpers are stopped, eleven
loopback ports are free. Parent disks, earlier evidence and personal JSON retain
their original hashes. Production servers, the user's VPN, Windows networking
and GitHub were untouched.

Independent distributed hosts/phases, rotating sources, state exhaustion,
multiple moving clients, GUI apps, DPI and higher PPS/large packets remain
untested. Recovery remains experimental and off by default; bounded reflection
and repeated ciphertext linkability are unresolved.
