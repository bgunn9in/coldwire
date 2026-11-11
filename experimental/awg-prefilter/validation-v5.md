# Bounded smoothing and lab transport controls

English | [Русский](validation-v5.ru.md)

Test date: 11 November 2026. IFB/TBF smoothing did not meet all admission
criteria. A 256 KiB queue dropped useful traffic. A 1 MiB queue preserved
the requested upload rate in the paced tests, but used more CPU and dropped
client packets at peak load. Neither becomes a default. The filter, guard
example and production installers are unchanged.

[results-v5.json](results-v5.json) contains 61 traffic trials, six arrival
captures, three roaming cases, rejection/recovery checks and fragmentation
controls. The [previous report](validation-v4.md) covers token-bucket tuning.

## Lab and method

Each series used four isolated QEMU 11.1.3/WHPX VMs with 1 vCPU and 1024 MiB
RAM each. New copy-on-write disks preserved the earlier results. The entry,
exit and client ran Debian 13 with Linux 6.12.116; the noise VM ran Linux
6.12.115. Workload traffic stayed between VMs; management used localhost.
The unchanged v3 filter binaries were verified by SHA-256, without a rebuild.
Their earlier 16/23 offline tests were not rerun for this queue experiment.

The initial series had five pilots and 20 paced trials. Its six separate
captures measured actual arrival windows, beyond the sender's syscall rate.
The localhost switch had not set `TCP_NODELAY` on accepted sockets. QEMU's
socket backend already sets it; the source hash is recorded in the JSON.
The second series enabled and checked that option on the switch as well.
It added 16 paced trials, four shared-NAT cases, eight unpaced uploads and
eight paced downloads. Guests also rebooted between series. Jitter remained
with the option enabled; these measurements do not identify Nagle as its cause.

TCP measured eight seconds after a one-second warmup. The requested rate
was 100 Mbit/s, or 50 Mbit/s per client behind one NAT, with a 5% tolerance.
Main comparisons used two repetitions with reversed policy order; shared-NAT
cases used one run per mode. Noise started about one second before TCP and
ran for twelve seconds at 10000 packets/s. It offered bursts of up to 4096
packets, using a fixed random 256-byte payload per run. All senders achieved
their requested average rate within 1%.

The selected IFB path preceded the existing guard and grouped NFQUEUE build.
TBF used `rate 200mbit burst 65536 limit 262144` or `limit 1048576`.
Its byte limit covers queued packet data, not total kernel memory. A byte
rate and an initial burst allowance do not impose a uniform packet rate.
See [TBF](https://man7.org/linux/man-pages/man8/tc-tbf.8.html) and the
[IFB redirect example](https://man7.org/linux/man-pages/man8/tc-mirred.8.html).
The guard kept aggregate 50000/5000 and tuple 35000/3500 packets/s/burst.
The smaller `burst512` guard appeared only in the initial series.

## Counter boundaries and actual arrivals

Before and after each trial, a temporary TC gate stopped new selected
ingress traffic. Existing IFB and NFQUEUE packets drained before two stable
packet-counter snapshots were collected. The sender's queue was also drained.
TC origin counts preceded IFB; nftables counts bracketed the guard. These
separated shaper drops, guard drops and NFQUEUE drops. IP labels were
instrumentation, with other client-source addresses following the same
shaping path. Packet counters and grouping ratios cover the full trial,
including noise outside the TCP sample.

All 47 filtered traffic trials had exact post-guard accounting: inspected
packets plus queue and netlink-user drops equalled the post-guard counts.
The earlier eight-packet discrepancy did not recur. This supports the new
collection method; it does not isolate the cause of the old discrepancy.

A cold-start diagnostic offered 40000 packets but only 38237 reached entry.
It is retained separately and excluded from comparisons; its cause was not
isolated. Later trials warmed neighbor reachability first. One second-series
DNAT/shared-NAT case still missed 604 of 120000 packets before the entry's TC
counter. All 61 traffic trials stayed within the 1% delivery criterion, with
zero switch drops. The stricter 0.1% diagnostic flag is retained separately.

The six arrival captures had no capture-buffer drops and matched entry TC
counts. They observed 39885 to 40000 of 40000 offered packets per case.
Source-side burst duration differed between one and 64 ports and did not
describe the receiver's burst. These captures belong to the initial switch
series; they are not an arrival trace of the later performance runs.

## Paced upload and CPU

The remaining tables use only the second series with `TCP_NODELAY` enabled.
Noise was 10000 packets/s. Cells give first/second runs. All 16 upload matrix
trials had zero NFQUEUE drops, including the unchanged baseline.

| Policy | Delivered Mbit/s | Whole entry CPU, % of one core | Client packets dropped before NFQUEUE |
|---|---:|---:|---:|
| DNAT | 101.60 / 103.30 | 8.20 / 6.85 | 0 / 0 |
| Guard + grouped filter | 102.75 / 102.85 | 26.45 / 26.15 | 0 / 0 |
| IFB 256 KiB + guard/filter | 79.85 / 99.51 | 28.68 / 38.95 | 219 / 96 |
| IFB 1 MiB + guard/filter | 100.12 / 102.46 | 41.80 / 40.83 | 0 / 0 |

At the same requested upload rate, filter process CPU was 11.51/11.41%
without IFB and 27.65/27.05% with the 1 MiB queue. Verdicts per submission
fell from 14.55/14.43 to 5.07/4.86, requiring more submission calls per
inspected packet. This experiment did not separate every source of added
CPU cost. CPU samples include warmup and collection overhead; they describe
this host and do not predict VPS usage.

With two clients behind one NAT, the requested rates were 50 Mbit/s each.
All four cases had zero NFQUEUE drops.

| Policy | Client 1 / client 2, Mbit/s | Client packets dropped before NFQUEUE |
|---|---:|---:|
| DNAT | 50.36 / 51.80 | 0 |
| Guard + grouped filter | 50.03 / 50.04 | 0 |
| IFB 256 KiB + guard/filter | 49.89 / 45.32 | 336 |
| IFB 1 MiB + guard/filter | 49.96 / 49.96 | 0 |

## Maximum upload and reverse traffic

Unpaced TCP exposed client losses with both queue sizes. Whole entry CPU
with the 1 MiB queue reached 72.71/71.61%, versus 31.51/33.01% for the
guarded filter alone.

| Policy | Delivered Mbit/s | NFQUEUE drops | Client packets dropped before NFQUEUE |
|---|---:|---:|---:|
| DNAT | 138.53 / 141.85 | 0 / 0 | 0 / 0 |
| Guard + grouped filter | 158.93 / 173.10 | 1609 / 1556 | 0 / 0 |
| IFB 256 KiB + guard/filter | 109.10 / 106.08 | 0 / 0 | 237 / 198 |
| IFB 1 MiB + guard/filter | 151.73 / 150.12 | 0 / 0 | 362 / 268 |

Five of eight reverse runs missed the requested 100 Mbit/s within 5%, across
policies. They cannot support a CPU comparison at matched delivered rates.
The small queue also failed to prevent NFQUEUE overflow in one reverse run.

| Policy | Download Mbit/s | NFQUEUE drops | Client packets dropped before NFQUEUE |
|---|---:|---:|---:|
| DNAT | 106.30 / 103.94 | 0 / 0 | 0 / 0 |
| Guard + grouped filter | 98.15 / 81.27 | 0 / 0 | 0 / 0 |
| IFB 256 KiB + guard/filter | 108.01 / 87.43 | 1885 / 0 | 74 / 0 |
| IFB 1 MiB + guard/filter | 100.27 / 89.80 | 0 / 0 | 0 / 0 |

Across all 61 traffic trials, 6095 of 6100 pings received replies.
Percentiles use sorted index `min(n-1, floor(p*n))`; p99 is the sample
maximum with at most 100 replies. Latency varied widely in both series.
No reliable WAN latency or peak-throughput benefit was established.

## Roaming, rejection and fragments

The guarded filter and both IFB variants passed IP/UDP-port changes during
64-port noise. All 60 post-change/restore probes received replies. A second
client held 50.13, 50.08 and 49.98 Mbit/s respectively. No source-IP allowlist
or admission cache was added.

With IFB present, wrong HPK and an unregistered key could not use the VPN.
All 100 altered packets with a captured transport prefix still passed the
partial filter without a key file at the sender. Killing the worker closed
filtered traffic. Removing only the experimental configuration restored
DNAT, removed IFB and preserved the main relay table.

The first recovery harness started a replacement client while the queue was
still fail-closed. Its first probe failed; later probes worked without more
relay changes. The corrected check restores DNAT before starting that client
and passed. Worst-case reconnect time was not measured.

A separate broad UDP counter measured 200 fragments making up 100 invalid
datagrams. The TC classifier using a UDP destination port matched none of
those fragments in this kernel. After reassembly, NFQUEUE rejected all 100
invalid headers. The unfragmented control matched all 100 packets at TC and
rejected all 100 at the filter. Thus this port-selected shaper leaves a path
to reassembly outside its queue; the HPK check itself remained in force.

## Decision

Keep IFB/TBF out of the default setup. The tested small queue loses useful
traffic, the larger queue increases CPU and still drops client bursts, and
the port selector misses fragmented traffic. Byte shaping did not guarantee
zero NFQUEUE drops. A kernel queue budget is additional to process RSS.

Further work should profile the receive/verdict cost before choosing another
queue policy. Fragment handling would need its own admission tests. Neither
a trusted-flow cache nor a kernel crypto implementation was added. The
strict I1/Jc behavior and partial-authentication limits are unchanged.

Both four-VM series and their helpers were stopped; all ten reused localhost
ports were released after each series. No production deployment was made.
Physical GUI clients, real VPS performance, DPI resistance and sustained
distributed floods remain untested.
