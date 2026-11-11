# Kernel guard burst and rate study

English | [Русский](validation-v4.ru.md)

Test date: 11 November 2026. Smaller token-bucket bursts removed NFQUEUE
overflow in the tested maximum-rate runs, but also dropped client packets
before the queue. Lowering the sustained rate reduced useful throughput.
These results do not establish a safe universal preset. The public guard
example is unchanged, and the normal installers still use ordinary DNAT.

[results-v4.json](results-v4.json) contains all 66 traffic trials, per-source
packet counts, guest CPU measurements, roaming and recovery checks.
The [previous report](validation-v3.md) covers the optional grouped build.

## Method

Four isolated QEMU/WHPX VMs each had 1 vCPU and 1024 MiB RAM. Copy-on-write
disks preserved the earlier lab. The entry reported Debian 13.7, Linux
6.12.116, OpenSSL 3.5.7, libnetfilter_queue 1.0.5 and nftables 1.1.3.
The previous study used Linux 6.12.115; comparisons here use runs from this
study. Traffic and management stayed within the local lab.

Both filter binaries were reused from v3 and their SHA-256 hashes checked.
Their source hashes still match. The 16 ordinary and 23 grouped offline
tests, including ASan/UBSan, passed in v3; those unchanged tests were not
rerun for this rate-setting experiment. The grouped build remains optional.

All policies kept the same 4096-entry set and five-second idle expiry.
A tuple is a source IP and UDP source port. These are load buckets, so
changing either creates a new bucket without proving client identity.
See the nftables documentation on
[per-element rate limiting](https://wiki.nftables.org/wiki-nftables/index.php/Meters).

| Policy | Aggregate packets/s | Aggregate burst, packets | Tuple packets/s | Tuple burst, packets |
|---|---:|---:|---:|---:|
| baseline | 50000 | 5000 | 35000 | 3500 |
| burst512 | 50000 | 512 | 35000 | 256 |
| burst128 | 50000 | 128 | 35000 | 64 |
| rate24000 | 24000 | 512 | 16000 | 256 |

TCP measured eight seconds after a one-second warmup. Paced tests requested
100 Mbit/s, or 50 Mbit/s for each of two clients behind one NAT. Their
goodput criterion was within 5% of the requested rate. Unpaced tests imposed
no TCP bitrate limit. Main comparisons had two repetitions with reversed
policy order; shared-NAT cases had one run per combination.

The 66 trials comprise four steady-noise pilots, four burst pilots, 24 paced
matrix runs, six shared-NAT runs, eight unpaced screening runs, four paced
individual-build controls and 16 unpaced build controls.

Noise ran for twelve seconds, starting about one second before TCP. A
steady-noise pilot produced no queue drops at 100 Mbit/s. Later tests
offered bursts of up to 4096 UDP packets at an average 5000 or 10000
packets/s. A native sender used `sendmmsg` groups of up to 64 packets and
absolute sleeps after each offered burst. Its 256-byte payload was randomly
chosen once per run. Every sender met its average rate within 1%.

Recorded send durations include the shorter final burst. They do not
measure burst duration at the receiver. Using 64 source ports also changed
sender timing, so differences from single-port runs cannot be attributed
solely to the number of rate buckets. The local switch recorded zero drops
in all 66 trials.

## Loss accounting

Counter-only nftables chains observed client-origin and noise-origin packets
before the guard at priority -320 and after it at -301. NFQUEUE ran at -300.
Their differences identify early drops by origin; queue counters alone
cannot show them. Counts cover the trial, including noise outside the TCP
measurement window. Filter and guard settings were reset for each trial.

Entry GRO was enabled, but UDP GRO forwarding, TX checksum offload, GSO and
UDP segmentation were disabled. In 65 trials, inspected packets plus queue
and netlink-user drops equalled post-guard skb counts. One clean
`rate24000` trial recorded 92032 post-guard packets and 92024 inspections,
a difference of eight (0.0087%). Snapshots were sequential; the cause was
not isolated. This does not establish accounting equivalence on other
offload paths.

## Paced traffic

Cells show first/second runs of the grouped build. All 24 paced matrix
trials had zero queue drops, including the unchanged baseline.
At 5000 noise packets/s, `rate24000` delivered 78.46/80.11 Mbit/s.

| Policy | Noise packets/s | Useful Mbit/s | Client-origin early drops | Ping p99, ms |
|---|---:|---:|---:|---:|
| baseline | 0 | 100.06 / 99.90 | 0 / 0 | 20.4 / 25.2 |
| baseline | 10000 | 100.19 / 99.97 | 0 / 0 | 29.2 / 26.1 |
| burst512 | 0 | 100.19 / 100.06 | 0 / 0 | 24.7 / 20.0 |
| burst512 | 10000 | 100.07 / 100.06 | 0 / 0 | 31.5 / 36.3 |
| burst128 | 0 | 99.85 / 100.04 | 204 / 164 | 24.0 / 19.0 |
| burst128 | 10000 | 100.39 / 100.05 | 245 / 222 | 37.9 / 25.8 |
| rate24000 | 0 | 100.06 / 100.05 | 0 / 0 | 23.7 / 19.9 |
| rate24000 | 10000 | 73.48 / 74.50 | 442 / 348 | 29.4 / 24.2 |

`burst128` dropped client packets even without noise while TCP still met
the bitrate target. `rate24000` failed that target under noise. Its lower
CPU use in some trials came with less useful traffic, so it does not show
an efficiency improvement. Per-trial CPU, RSS and raw tick deltas are in
the JSON; they describe this virtual host environment.

Two clients behind one NAT shared the requested 100 Mbit/s as follows.
All six cases had zero queue drops. Noise averaged 10000 packets/s.

| Policy | Noise source ports | Client 1 / client 2, Mbit/s | Client-origin early drops |
|---|---:|---:|---:|
| baseline | 1 | 49.98 / 50.11 | 0 |
| baseline | 64 | 50.13 / 50.23 | 0 |
| burst512 | 1 | 49.98 / 49.98 | 0 |
| burst512 | 64 | 50.11 / 50.11 | 22 |
| rate24000 | 1 | 41.93 / 37.99 | 1047 |
| rate24000 | 64 | 37.91 / 36.15 | 1192 |

## Maximum-rate control

An eight-run unpaced screen was followed by 16 control runs with both
builds, clean traffic and 10000 noise packets/s. The table gives the noisy
controls, first/second run. `burst512` eliminated queue overflow here while
moving some client losses ahead of the queue.

| Build | Policy | Useful Mbit/s | Queue drops | Client-origin early drops |
|---|---|---:|---:|---:|
| Individual | baseline | 146.73 / 144.96 | 1963 / 870 | 0 / 0 |
| Individual | burst512 | 149.38 / 144.17 | 0 / 0 | 99 / 83 |
| Grouped | baseline | 212.47 / 181.19 | 3138 / 1935 | 0 / 0 |
| Grouped | burst512 | 152.44 / 177.19 | 0 / 0 | 43 / 179 |

Clean `burst512` controls also dropped 33/41 client-origin packets with
individual submissions and 122/99 with grouping. Grouped clean baseline
throughput ranged from 152.91 to 243.30 Mbit/s, versus 153.32 to 159.26
with `burst512`. The spread and short samples leave peak performance
unresolved; this candidate can suppress client bursts.

Every trial sent 100 pings at 20 ms intervals. Across all 66 trials,
6574 of 6600 received replies. Percentiles use sorted sample index
`min(n-1, floor(p*n))`; with at most 100 replies, p99 is the sample maximum.
Paced p99 did not improve consistently with smaller bursts. These short
virtual-network samples provide no WAN latency guarantee.

## Roaming, rejection and recovery

Separate `baseline`, `burst512` and `rate24000` trials changed one client's
outer IP and UDP port during 10000 packets/s of 64-port noise, then restored
them. All 60 probes after those changes received replies. A second client
held 50.04, 50.02 and 50.03 Mbit/s respectively. This tests recovery from
address changes without a source-IP allowlist.

Recovery checks passed for two fresh native AWG clients behind NAT,
different packet sizes, roaming and reassignment of the old outer tuple.
Wrong HPK and an unregistered key could not use the VPN. The full 4096-entry
set blocked a new tuple and recovered after expiry. Killing the filter
closed traffic; deleting only experimental tables restored DNAT and left
the main relay table unchanged.

The partial-authentication limitation remains: all 100 packets with a
captured transport prefix and altered payload passed the filter without
the sender holding its key file. Startup captures again showed six
unrecognized camouflage packets: DNAT forwarded them, the strict filter
dropped them. Forwarded payloads were unchanged. This changes the packet
pattern between entry and exit; DPI resistance was not tested.

All four VMs and both lab helpers were stopped, and all ten localhost ports
were released. Live servers, the user's VPN and personal bypass JSON were
not changed.

## Decision and next experiment

Reject `rate24000` for the tested 100 Mbit/s target and `burst128` for its
clean-client drops. Keep `burst512` as a lab candidate only. Assess admission
by client-origin early drops, delivered goodput and latency alongside queue
drops. No new preset or production service was installed.

Before another tuning attempt, make counter collection quiescent and
measure the actual arrival burst. A bounded smoothing queue could then be
compared at the same useful rate, including several clients and address
changes; its delay and memory cost would need measurement. Physical GUI
clients, long runs, real VPS performance and distributed-source traffic
remain outside this study.
