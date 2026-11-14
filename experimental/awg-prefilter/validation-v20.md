# Client roaming with WAN delay and jitter

English | [Русский](validation-v20.ru.md)

Test date: 14 November 2026. The unchanged v19 admission rules do not give
lossless roaming throughout the tested delay range. At 300 ms added RTT,
the initial guard discarded 0 to 187 client packets across the primary
tests and repeats. Fresh admission took about 399 to 910 ms after the gateway move.
The twelve primary tests passed the full service criterion in 5 cases.
The entry guard had zero client discards in 9 of those twelve.
Some additional reported UDP losses belong to test-receiver accounting;
the separate capture control below checks actual delivery through B.
See [data](results-v20.json) and the [v19 local-link controls](validation-v19.md).

## Setup and acceptance

Four fresh COW Debian 13 guests ran under QEMU 11.1.3/WHPX with one vCPU
and 1024 MiB RAM each. The C classifier, patched AWG receiver, lease agents
and packet rules were unchanged from commit `a285038`. Both native client
profiles, binaries, keys and ports 32497/32498 were unchanged. Only the lab
gateway changed client 1's source IP, or its IP and NAT port, 25 seconds
after useful traffic began. The second profile continued to send probes.

Noise offered 25,000 datagrams/s for 70 seconds from 64 ports at one lab IP,
in 4096-packet bursts. It reused a freshly captured transport prefix with
altered ciphertext. The entry must not grant it a lease. Useful UDP sent
128-byte payloads at 6000 packets/s for 60 seconds with 1000-us pacing.
Each profile sent 100 ICMP probes with 500-ms spacing and a one-second
reply deadline. Inner captures were checked against the probe results.
Useful PPS counts application datagrams; it is not a direct count of outer
AWG packets or kernel skbs when offloads are active.

The final matrix uses `iperf3 -u -b 6144000 -l 128 --pacing-timer 1000
-t 60 -O 0 -J`. No first second is excluded. A small exit-only addition
to the resident sampler records the receive-drop counters of UDP sockets
32497, 5201 and 5202 by inode. It runs once per nominal 250-ms sample,
without spawning processes. This changes the measurement helper, not AWG.

Full acceptance requires noise sender/switch/entry counts and arrival
rate within 1%, useful sender rate within 1% and receiver rate within 5%,
zero reported UDP loss, 200/200 probes matching captures, no client guard,
control guard, NFQUEUE/netlink or emulator-queue drops, and whole-VM CPU
at most 90% in every stored sample and four-sample window. CPU includes
the first noise burst. No CPU quota, affinity, host routes, firewall,
power or WSL settings were changed.

## Delay placement

Only the exit's lab interface `enp0s3` is impaired. Its egress netem adds
half the target RTT. A flower rule redirects IPv4 from A to B into
`ifb-wan20`, whose netem adds the other half. Both VPN datagrams and the
mutual-TLS control stream traverse the delay. The separate management
interface and the client-to-entry noise path are unaffected.

Each netem queue holds at most 16,384 packets. No random loss, rate limit
or explicit duplication was configured. Fixed-delay tests use 25, 75 or
150 ms per direction. Jitter tests add normal variation of 5, 15 or 30 ms
per direction. The per-direction seeds are retained in the data. Twenty
physical A-to-B pings check actual RTT before each run; the table reports
their median. Netem jitter can reorder packets and kernel timers affect
the achieved delay. See the [upstream netem manual](https://github.com/iproute2/iproute2/blob/main/man/man8/tc-netem.8).

## Final full-window matrix

| RTT target / measured ms | Jitter each way ms | Move | Guard loss | UDP reported loss | B rcvbuf | Ping | Peak CPU % | Grant ms* | Pass |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| 50 / 52.4 | 0 | IP+NAT port | 0 | 0 | 0 | 200/200 | 83.33 | 339 | yes |
| 50 / 52.4 | 0 | IP | 0 | 0 | 0 | 200/200 | 83.33 | 333 | yes |
| 50 / 53.0 | 5 | IP+NAT port | 0 | 0 | 0 | 200/200 | 84.00 | 369 | yes |
| 50 / 52.8 | 5 | IP | 0 | 63 | 0 | 200/200 | 76.19 | 352 | no |
| 150 / 152.0 | 0 | IP+NAT port | 0 | 0 | 0 | 200/200 | 80.95 | 437 | yes |
| 150 / 152.0 | 0 | IP | 0 | 0 | 0 | 200/200 | 73.91 | 434 | yes |
| 150 / 158.0 | 15 | IP+NAT port | 0 | 6 | 0 | 200/200 | 77.27 | 494 | no |
| 150 / 159.0 | 15 | IP | 0 | 5 | 0 | 200/200 | 78.95 | 479 | no |
| 300 / 302.0 | 0 | IP+NAT port | 77 | 77 | 0 | 200/200 | 81.48 | 849 | no |
| 300 / 302.0 | 0 | IP | 74 | 74 | 0 | 200/200 | 82.14 | 845 | no |
| 300 / 296.0 | 30 | IP+NAT port | 0 | 22 | 0 | 200/200 | 76.19 | 641 | no |
| 300 / 297.0 | 30 | IP | 187 | 272 | 0 | 200/200 | 85.19 | 910 | no |

*Grant time is approximate: A's first new-flow grant wall-clock minus the
gateway move-completion wall-clock. It is not a synchronized packet-latency
trace. The proof protocol itself still checks freshness on B's monotonic clock.

The two zero-added-delay controls used the same emulator path:

| RTT target / measured ms | Jitter each way ms | Move | Guard loss | UDP reported loss | B rcvbuf | Ping | Peak CPU % | Grant ms* | Pass |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| 0 / 2.1 | 0 | IP+NAT port | 0 | 0 | 0 | 200/200 | 77.27 | 282 | yes |
| 0 / 2.1 | 0 | IP | 0 | 0 | 0 | 200/200 | 80.77 | 279 | yes |

The 300-ms jitter case was repeated with a different seed in both move modes:

| RTT target / measured ms | Jitter each way ms | Move | Guard loss | UDP reported loss | B rcvbuf | Ping | Peak CPU % | Grant ms* | Pass |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| 300 / 319.5 | 30 | IP+NAT port | 0 | 107 | 0 | 199/200 | 76.19 | 399 | no |
| 300 / 319.5 | 30 | IP | 0 | 45 | 0 | 200/200 | 80.00 | 641 | no |

The full-window cohort comprises 16 completed tests. Each matched
1,750,000 noise datagrams at sender, switch and entry. Its peak whole-VM
CPU was 85.19%: entry 55.56%, exit 42.31%,
client 85.19% and noise guest 20.00%.
The data retain the individual rate and CPU checks; a failed service row
is not treated as a capacity pass because ping succeeded.

## Measurement correction and earlier attempts

The earlier 12 completed tests used `-O 1`. Under jitter iperf3 3.18
reported impossible negative loss counts: -225, -160, -36, -59.
Its UDP summary subtracts an omitted-period error estimate from the final
estimate; later arrivals can revise that earlier estimate. This explanation
follows the [upstream summary code](https://github.com/esnet/iperf/blob/3.18/src/iperf_api.c)
and [UDP receive accounting](https://github.com/esnet/iperf/blob/3.18/src/iperf_udp.c).
Those jitter values are retained as invalid loss estimates. They are
neither clamped to zero nor interpreted as real packet losses. A complete
matrix was then run with `-O 0` under new case names.

| RTT target / measured ms | Jitter each way ms | Move | Guard loss | UDP reported loss | B rcvbuf | Ping | Peak CPU % | Grant ms* | Pass |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| 0 / 2.1 | 0 | IP+NAT port | 0 | 0 | 0 | 200/200 | 82.14 | 257 | yes |
| 0 / 2.1 | 0 | IP | 0 | 0 | 0 | 200/200 | 82.14 | 261 | yes |
| 50 / 53.5 | 0 | IP+NAT port | 0 | 0 | 0 | 200/200 | 78.26 | 314 | yes |
| 50 / 52.7 | 0 | IP | 0 | 35 | 35 | 200/200 | 83.33 | 314 | no |
| 50 / 53.2 | 5 | IP+NAT port | 0 | -36 | 0 | 200/200 | 80.00 | 322 | no |
| 50 / 52.0 | 5 | IP | 0 | -59 | 0 | 200/200 | 82.14 | 338 | no |
| 150 / 153.0 | 0 | IP+NAT port | 0 | 0 | 0 | 200/200 | 85.71 | 429 | yes |
| 150 / 153.0 | 0 | IP | 0 | 0 | 0 | 200/200 | 80.00 | 416 | yes |
| 150 / 159.0 | 15 | IP+NAT port | 21 | -225 | 0 | 200/200 | 85.19 | 443 | no |
| 150 / 158.0 | 15 | IP | 0 | -160 | 0 | 200/200 | 82.76 | 482 | no |
| 300 / 302.0 | 0 | IP+NAT port | 613 | 613 | 0 | 200/200 | 87.50 | 824 | no |
| 300 / 302.0 | 0 | IP | 679 | 679 | 0 | 200/200 | 84.62 | 819 | no |

One early fixed-50-ms/IP attempt reported 35 lost UDP packets and exactly
35 exit `Udp.RcvbufErrors`, while the persistent AWG socket's drop counter
stayed zero. Its transient receiving test socket had already closed before
the final inventory. This suggests a receiver-buffer loss; the original
run does not provide per-socket proof. Later full-window runs retain the
per-socket samples separately. Raw negative reports and positive failures
are preserved rather than replaced by the repeats.

## Separate UDP delivery and return-path control

| RTT target / measured ms | Jitter each way ms | Move | Guard loss | UDP reported loss | B rcvbuf | Ping | Peak CPU % | Grant ms* | Pass |
|---|---:|---|---:|---:|---:|---:|---:|---:|---|
| 50 / 52.5 | 5 | IP | 0 | 35 | 0 | 199/200 | 85.19 | 378 | no |

A separate fixed-50-ms plus 5-ms-jitter/IP run captured every test datagram
at the sending tunnel and inside B. It counted 360,006 unique sent
and 360,006 unique received datagrams, with zero missing IDs,
duplicates or capture-kernel drops. Iperf still reported 35 lost packets
and credited 37 fewer datagrams than the capture. This demonstrates
that its aggregate loss value can differ from actual VPN delivery under
jitter. Closed-port counters also rose after the receiver ended. This
single control does not retrospectively correct every primary UDP result
or erase the earlier receive-buffer error.
The extra captures are excluded from the primary performance cohort;
their own CPU samples remain in the data.

Two ICMP replies did not reach the client: sequence 48 in the
300-ms jitter/port-change repeat and in this 50-ms diagnostic. B's inner
capture contains both requests and replies. Both cases had zero entry-guard
and NFQUEUE loss and exactly one new gateway `Udp.NoPorts`. The loss is
localized after B generated the reply. An old/new NAT or endpoint choice
is a plausible explanation, not proven by an outer-packet capture here.

## Interpretation and rollback

The initial guard's losses remain a protocol-path limit even with CPU
headroom. A moving tuple must wait for a fresh confirmation from B;
finite source/aggregate credits can run out before that response. The
source/aggregate sustained limits remain 1500/6000 packets/s with bursts
4096/1024, and unknown control messages retain their separate budget.
No guard, lease lifetime or security check was relaxed for these tests.

Network-loss counters, including any IFB receive drops, are retained in
the data. Netem queue drops and UDP receive-buffer errors are separate
counters. This series does not establish behavior for real WAN links,
physical GUI clients, cold startup under delay, distributed noise,
state exhaustion, adaptive attacks or sustained operation over hours.

Rollback removed the owned IFB, ingress rule and netem queues, restored
the exit's original fq_codel options and stock AWG binary/unit/environment,
ordinary DNAT, gateway NAT and client runtime. Both unchanged profiles
passed ordinary-DNAT probes. All four VMs and owned seed/switch processes
stopped; eleven loopback ports were free. Parent disks, personal JSON,
VPN sources/rules and previous v1 through v19 reports/data matched their
initial hashes. Live servers, the user's VPN and GitHub were untouched.
Raw captures and private profiles remain local.
