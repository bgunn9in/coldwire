# Verdict grouping experiment

English | [Русский](validation-v3.ru.md)

Test date is 11 November 2026. Grouping individual netlink verdict messages
reduced process CPU use at a matched 100 Mbit/s in this lab. Peak throughput
varied widely, and queue drops remained under noise. The grouped build is
optional. The default binary continues submitting one verdict at a time.

[results-v3.json](results-v3.json) contains every run, CPU tick deltas,
profiling counters, source/binary hashes and cleanup checks. The previous
source was rebuilt from commit `df37aeb` as an additional reference.

## Method and implementation

Four isolated Debian 13.7 VMs each had 1 vCPU and 1024 MiB RAM. Separate
copy-on-write disks preserved the earlier lab images and results. The lab
used the same AWG core, Linux 6.12.115, OpenSSL 3.5.7, libnetfilter_queue
1.0.5, nftables 1.1.3 and the localhost learning switch. All traffic tests
stayed between these VMs.

`PREFILTER_BATCH` enables `recvmmsg(MSG_WAITFORONE)` and groups up to 16
individual `NFQNL_MSG_VERDICT` messages into one `sendmsg` datagram. Each
message carries its own inspected packet ID and accept/drop decision.
The tail is flushed before the next blocking receive. Receive storage is
bounded at 16 × 8192 bytes. The copy limit remains 212 bytes, and kernel
GSO normalization remains enabled.

This uses the kernel's parsing of multiple netlink messages. The prefix
verdict API would apply one decision to all pending IDs through a boundary;
individual messages preserve decisions across gaps, mixed results and ID
wrap. [Kernel receive path](https://github.com/torvalds/linux/blob/v6.12/net/netfilter/nfnetlink.c),
[NFQUEUE API](https://www.netfilter.org/projects/libnetfilter_queue/doxygen/html/group__Queue.html).

## CPU at matched goodput

Each mode/direction had three uninstrumented runs at a requested 100 Mbit/s,
measuring six seconds after a one-second warmup. Mode order alternated.
All twelve cases met the requested rate within 0.25%. Values are medians.
Process CPU uses `/proc` ticks and each guest's `CLK_TCK`; entry CPU covers
the whole guest over the sampled interval, including warmup and collection
overhead.

| Mode | Direction | Mbit/s | Filter process CPU | Whole entry CPU | Verdicts per submission |
|---|---|---:|---:|---:|---:|
| Individual | Upload | 100.24 | 14.08% | 25.14% | 1.00 |
| Grouped | Upload | 100.04 | 10.08% | 21.55% | 9.12 |
| Individual | Download | 99.98 | 6.87% | 18.21% | 1.00 |
| Grouped | Download | 99.96 | 5.70% | 16.78% | 5.80 |

Matched-run RSS was 6444–6448 KiB for the individual build and 6496–6500 KiB
for the grouped build. Kernel socket, queue and rate-set memory is additional.
Separate instrumented runs are included in the JSON. Their clock-call
frequency differs between builds, so the table above uses ordinary builds.

## Maximum-rate and noise runs

Unpaced TCP used three runs per mode/direction, eight measured seconds after
a one-second warmup, with rotated mode order. Median upload/download rates
were 181.13/141.15 Mbit/s for the individual build and 152.66/129.50 Mbit/s
for grouping. Upload ranges were 144.77–244.84 and 133.89–255.24 Mbit/s.
DNAT medians were 141.34/124.26, and the rebuilt previous source gave
143.13/129.50 Mbit/s. This spread leaves the peak-throughput benefit unresolved.

Controlled noise used random 256-byte UDP payloads and the unchanged kernel
guard example for both filter modes. Each sender achieved its requested
rate within 1%. The sender ran for twelve seconds. TCP measured eight seconds
after a one-second warmup, starting about one second after noise began.
The cells below show the first/second run in Mbit/s.

| Noise packets/s | DNAT | Guard + individual | Guard + grouped |
|---|---:|---:|---:|
| 5000 | 102.14 / 102.62 | 144.21 / 140.08 | 144.75 / 149.75 |
| 10000 | 75.60 / 67.37 | 139.29 / 133.39 | 138.75 / 247.31 |

At 5000 packets/s, the counters sampled at the end of TCP recorded 0 and
1016 kernel queue drops for individual submissions, and 0 and 0 for grouping.
At 10,000 packets/s, the respective
counts were 1480/855 and 1117/1308. Sampled netlink user drops and switch
drops were zero. Every post-load client probe passed. Grouping therefore
leaves queue admission and burst calibration as further work.

## Latency

Each cell shows the range across two runs of 100 pings at 20 ms intervals.
All 1200 probes received replies. Noise senders achieved 10,000 packets/s
within 1%.

Percentiles use sorted sample index `min(n-1, floor(p*n))`; with 100 replies,
p99 is the maximum of that short sample.

| Mode | Noise packets/s | p95 ms | p99 ms |
|---|---:|---:|---:|
| DNAT | 0 | 1.80–2.12 | 2.27–2.30 |
| Individual | 0 | 1.90–2.33 | 2.28–3.12 |
| Grouped | 0 | 1.90–2.07 | 2.22–2.42 |
| DNAT | 10000 | 23.20–25.50 | 29.90–30.90 |
| Individual | 10000 | 4.39–5.53 | 21.90–23.10 |
| Grouped | 10000 | 4.24–5.89 | 26.50–26.80 |

The idle tests showed no fixed batch-fill delay. Grouped p99 was higher in
these two noise samples. Short virtual-network runs provide no WAN latency
guarantee.

## Rejection and recovery

The ordinary build passed 16 offline tests, and the grouped build passed
23, in both optimized and ASan/UBSan configurations. The extra checks decode
actual encoded verdict messages and cover mixed decisions, ID gaps/wrap,
interrupted sends, failures before/after a completed flush, short sends and
empty input. The project's 50 Python tests also passed without skips.

A live mixed stream sent 2000 packets of each of five kinds. Both builds
delivered zero random, wrong-HPK or invalid-MAC1 packets to B. Each delivered
all 2000 MAC1-correct/Noise-invalid packets and all 2000 forged transport
packets. That partial-check limitation persists. A separate keyless
captured-prefix test again admitted all 100 altered packets.

Both guarded modes passed two-client/shared-NAT, IP/port roaming and
outer-tuple reassignment tests. Wrong HPK and an unregistered client key
could not use the VPN. All 100 backend-spoofing packets in the original
direction were checked and dropped. A server-initiated handshake produced
an incoming response that passed MAC1 checking in the grouped build.

The 4096-entry flow-set limit rejected a new tuple while full and recovered
after idle expiry. Killing the queue process stopped filtered traffic.
Deleting the experimental tables restored DNAT and preserved the ordinary
relay rules. Captures confirmed unchanged forwarded payloads and continued
strict rejection of startup camouflage packets between entry and exit.

Physical GUI clients, DPI resistance and long runs remain untested. The
normal installers continue using DNAT. All four lab VMs and both helpers
were stopped, and their ten localhost ports were released.
