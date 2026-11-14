# Multiple noise flows and useful high-PPS traffic

English | [Русский](validation-v17.ru.md)

Test date: 13 November 2026. The 15k/30k protective guard does not reliably
preserve clients against noise spread across UDP source ports. With eight
flows at 25,000 offered packets/s, one qualified trial discarded 5488 client
packets in the aggregate limiter, lost ten echo replies and reduced one
50-Mbit/s stream to 19.31 Mbit/s. NFQUEUE drops were zero and peak VM CPU
was 55.17%. Staying below the CPU threshold did not preserve service.

Keep the [profile](lab-kernel-guard-protect15k.nft.example) experimental and
disabled in normal installers. Its rule body and the filter are unchanged.
[Results and checks](results-v17.json).

## Workload and qualification

Four fresh COW guests each had one vCPU and 1024 MiB RAM, Debian 13 kernel
6.12.116, QEMU 11.1.3/WHPX and the existing virtual Ethernet layout. Two
native AWG profiles shared one client VM. Entry retained modern Virtio,
RX/TX 256, NAPI 64, `fq_codel`, queue 4096, copy 212 and grouped individual
verdicts. No CPU quota, affinity or host-network change was applied.

Noise used one source IP with 1, 2, 8 or 64 UDP source ports, sharing a total
25,000 packets/s. This tests multiple tuples, not multiple source machines
or distributed IPs. Each noise run sent 1,750,000 fixed 256-byte datagrams
over seventy seconds in bursts up to 4096. Both recognizable-junk fixtures
from [v16](validation-v16.md) were retained: valid MAC1/invalid Noise body
and a fresh transport prefix with altered payload. The exit authenticates
VPN traffic; passing the header filter does not authenticate a client.

TCP requested 50 Mbit/s per profile in mixed directions. High-PPS tests
used real UDP inside AWG: 128-byte application payloads, sixty seconds
after one omitted second and a 1000-us iperf pacing timer. Each profile
sent 100 ICMP probes at 500-ms intervals with a one-second reply budget,
including when only the other profile carried bulk traffic.

A TCP pass required each stream within 5% of its target. UDP required a
sender rate within 1% of requested PPS, receiver rate within 5%, and zero
reported UDP loss. Both modes required 200/200 echoes matching captures,
zero NFQUEUE/netlink/client-guard/shaper discards, and every whole-VM CPU
sample and four-sample window at or below 90%. CPU was sampled nominally
every 250 ms; no process census, queue polling or fprobe ran during load.
The threshold includes the generator and observer, not just the entry.

Completed trials: 31; complete rate observation:
25; full service passes:
5. All trials offered 31500000
noise datagrams in total. The 12 qualified noise trials offered
21000000 datagrams. Six initial multi-flow
acquisitions lacked native timing and are listed separately below.

## Noise split across ports

The original switch counted noise timing only for source port 46000.
Multi-flow generation uses ports 40000–40063, so its native timing records
were empty. Five initial acquisitions had matching sender/entry counts;
the eight-flow prefix acquisition had 17 fewer packets at entry. The classifier now
recognizes any source port for the same isolated source/target IPs, target
port and UDP length. Forwarding is unchanged. The old binary fails the
new multiport counter regression; the corrected binary passes the full
socket and native self-tests. All four disposable guests were restarted
to reconnect, then 2/8/64-flow measurements were repeated. Missing timing
was not accepted as a passing rate measurement.

Every qualified noise trial matched sender, switch and entry counts of
1,750,000, with sender and native arrival means within 1% of 25,000/s and
zero switch drops. The table retains both successful and failed service
results; Mbit/s lists upload and download separately.

| Noise flows | Fixture | Series | Mbit/s each | Peak VM CPU % | Early client discards | NFQUEUE drops | Echoes | Pass |
|---:|---|---|---:|---:|---:|---:|---:|---|
| 1 | prefix | initial | 50.57 / 50.59 | 75.00 | 284 | 0 | 200/200 | no |
| 1 | MAC1 | initial | 49.99 / 50.00 | 44.44 | 0 | 0 | 200/200 | yes |
| 2 | prefix | fixed | 49.99 / 50.00 | 48.15 | 0 | 0 | 200/200 | yes |
| 2 | MAC1 | fixed | 50.74 / 50.75 | 80.00 | 0 | 0 | 200/200 | yes |
| 8 | prefix | fixed | 17.53 / 50.00 | 58.33 | 5881 | 0 | 186/200 | no |
| 8 | MAC1 | fixed | 19.31 / 50.00 | 55.17 | 5488 | 0 | 190/200 | no |
| 64 | prefix | fixed | 18.33 / 50.00 | 60.00 | 6105 | 0 | 184/200 | no |
| 64 | prefix | repeat | 14.66 / 50.00 | 68.00 | 4400 | 0 | 193/200 | no |
| 64 | MAC1 | fixed | 18.24 / 50.00 | 56.00 | 5252 | 0 | 186/200 | no |
| 64 | MAC1 | repeat | 14.64 / 50.17 | 59.26 | 3834 | 0 | 196/200 | no |

At eight and sixty-four flows, individual flow buckets no longer removed
enough noise. The common aggregate bucket then discarded client traffic
along with noise. In the 5488-client-discard example, all 330,523 early
discards were in the aggregate bucket; the per-flow discard counter was
zero. Client pre/post counters identify the client share of that total.
The aggregate counter alone cannot assign its discards to a client.

The initial one-flow prefix control also lost 284 client packets before
NFQUEUE despite keeping all echoes and both TCP rates. The successful
eleven-trial series in v16 remains valid for those runs. This control
shows that the same limits do not guarantee client preservation under
different arrival bursts. Increasing shared limits would require another
CPU/queue test and would not itself distinguish clients from noise.

## Useful traffic with high PPS

PPS here describes UDP application payload packets. It is not a direct
measurement of outer AWG wire PPS. The JSON retains separate iperf sender
and receiver summaries plus packet/byte counters before and after the
guard. Those kernel counters count observed skbs. UDP omission boundaries
can also give slightly different sender/receiver totals; equality was
not forced. [iperf3 summary fields](https://github.com/esnet/iperf/blob/3.18/src/iperf_api.c).

Modes are ordinary `dnat`, the guard plus filter (`protect15k`), and the
same guard without NFQUEUE (`kernel15k`). CPU columns list client C, entry A
and exit B; acceptance still checks all four VMs.

| Mode | Clients × PPS | Delivered PPS | UDP loss % | Early client discards | CPU C/A/B % | Echoes | Pass |
|---|---|---|---|---|---|---|---|
| dnat | 1 × 6000 | 6000 | 0.000 | 0 | 81.48 / 4.35 / 21.43 | 200/200 | yes |
| protect15k | 1 × 6000 | 6000 | 0.002 | 0 | 84.62 / 30.00 / 24.14 | 200/200 | no |
| dnat | 1 × 8000 | 8000 | 0.000 | 0 | 92.31 / 8.70 / 25.93 | 200/200 | no |
| protect15k | 1 × 8000 | 8000 | 0.000 | 0 | 88.00 / 31.03 / 26.92 | 200/200 | yes |
| dnat | 1 × 12000 | 12000 | 0.000 | 0 | 100.00 / 4.55 / 28.57 | 200/200 | no |
| protect15k | 1 × 12000 | 11970 | 0.252 | 1363 | 100.00 / 34.48 / 32.14 | 200/200 | no |
| dnat | 1 × 20000 | 14673 | 26.638 | 0 | 100.00 / 8.70 / 37.04 | 181/200 | no |
| kernel15k | 1 × 20000 | 12116 | 39.213 | 56204 | 100.00 / 9.09 / 28.57 | 158/200 | no |
| protect15k | 1 × 20000 | 14999 | 25.007 | 304571 | 100.00 / 40.00 / 34.48 | 168/200 | no |
| dnat | 2 × 4000 | 4000 / 4000 | 0.000 / 0.000 | 0 | 91.30 / 8.70 / 31.03 | 200/200 | no |
| protect15k | 2 × 4000 | 4000 / 4000 | 0.000 / 0.000 | 0 | 92.31 / 25.93 / 27.59 | 200/200 | no |
| dnat | 2 × 10000 | 3267 / 3105 | 67.941 / 69.690 | 0 | 100.00 / 4.35 / 24.14 | 61/200 | no |
| protect15k | 2 × 10000 | 3352 / 3401 | 67.125 / 66.635 | 0 | 100.00 / 31.03 / 25.93 | 76/200 | no |

The 12,000-PPS DNAT control delivered its target without reported UDP loss,
while client CPU reached 100%. At 20,000 requested PPS, that control had
26.638% UDP loss and missing echoes with no entry limiter. These baseline
failures prevent treating requested application PPS as proven relay capacity
within the CPU budget. Two profiles on the
same single core also compete for that budget.

With the protective guard, the 20,000-PPS run counted 304,571 early client
discards in the per-flow bucket and zero aggregate or NFQUEUE discards.
At 12,000 PPS, it still discarded 1363 client packets: an average below
15,000/s does not guarantee that bursts fit the 512-packet allowance.
Sequential DNAT and filtered runs differed in client CPU and delivery;
their differences must not all be assigned to the filter. Lower-load
controls were retained to show operation with more source CPU headroom.
The filtered 6000-PPS control reported eight missing UDP packets despite
zero early-guard/NFQUEUE discards and CPU below 90%. The ICMP-only captures
do not locate those UDP gaps; that control also fails the zero-loss criterion.

## High PPS together with noise

Both trials below offered 25,000 noise packets/s. Noise used captured
prefixes; the listed UDP rates are useful application traffic.

| Noise | Mode | Clients × PPS | Delivered PPS | UDP loss % | Early client discards | CPU C/A/B % | Echoes | Pass |
|---|---|---|---|---|---|---|---|---|
| 8 | protect15k | 2 × 4000 | 3633 / 3632 | 9.171 / 9.200 | 44777 | 88.89 / 59.26 / 53.57 | 182/200 | no |
| 64 | protect15k | 1 × 10000 | 8673 | 13.273 | 74695 | 100.00 / 60.00 / 64.00 | 171/200 | no |

The guard has one shared aggregate budget. It provides neither a reserved
client allowance nor authenticated priority. These combined tests must
therefore be judged by delivery, early client discards and CPU together.
Zero NFQUEUE drops alone is insufficient.

## Initial acquisitions without native timing

These six runs retain their sender/entry counts and observed losses,
including that 17-packet deficit. They are excluded from capacity qualification because the switch
classifier missed their source ports. They were not silently replaced.

| Flows | Fixture | Mbit/s each | Early client discards | NFQUEUE | Echoes |
|---:|---|---:|---:|---:|---:|
| 2 | captured-prefix | 50.01 / 50.00 | 0 | 0 | 200/200 |
| 2 | valid-unknown | 49.98 / 50.21 | 0 | 0 | 200/200 |
| 8 | captured-prefix | 16.58 / 49.98 | 3907 | 1807 | 194/200 |
| 8 | valid-unknown | 15.07 / 50.00 | 5092 | 0 | 194/200 |
| 64 | captured-prefix | 16.93 / 50.00 | 5037 | 0 | 194/200 |
| 64 | valid-unknown | 16.48 / 50.00 | 4918 | 0 | 185/200 |

## Decision and cleanup

The tested guard can bound admitted work, but it cannot promise useful
service against the tested multi-flow noise. Do not enable it in the
normal installer. A next design would need a way to reserve work for
clients after authenticated confirmation from the exit, or another
measured isolation mechanism. A fixed public-IP allowlist would conflict
with roaming; no such allowlist was used here.

The probes and inner captures agreed in every completed trial, with zero
capture kernel drops: 5699/6200 replies overall.
Sender/receiver UDP summaries and early-drop counters answer different
questions and are preserved separately. Whole-host scheduling and burst
timing remain part of this QEMU/WHPX result. Physical GUI clients, real
VPS, distributed source IPs, adaptive attacks, set exhaustion and hours-long
operation were not tested. The strict I1/Jc policy and its camouflage
tradeoff are unchanged.

Rollback restored ordinary DNAT, client NAT/runtime settings, console and
scheduler controls, and the original guard template. Both original profiles
passed probes. Temporary tables were removed and capture jobs stopped. All four VMs
and owned host helpers stopped; eleven lab ports were free. Parent disks,
profile files, filter/QEMU binaries, prior v1–v16 reports and personal JSON
hashes matched. Live servers, the user's VPN, Windows networking and WSL
were untouched. GitHub was not updated.
