# Two clients, traffic direction and NAT rebinding

English | [Русский](validation-v10.ru.md)

Test date: 12 November 2026. The user raised the whole-VM CPU threshold
from 75% to **90%** during this study. Original samples were retained and
checked against both thresholds. Each of the four local VMs had 1 vCPU and
1024 MiB RAM; no CPU quota was applied.

Two independent native AWG clients shared a NAT and requested 50 Mbit/s
each. Every filtered run delivered about 100 Mbit/s in total, including
three runs in which one client's external IP and UDP port changed while
both TCP connections stayed active. Peak filtered CPU across all guests
was 76.92%, on the client VM. Entry peaked at 62.07%.

The requested noise rate was less reliable than in [v9](validation-v9.md).
Only 3 of 20 noisy trials passed the 25,000-packet/s rate check. The other
17 remain diagnostics at their measured rates. These results support
continued research on the grouped filter, but do not establish repeatable
25,000-packet/s performance across all tested traffic directions.

## Setup and acceptance checks

The [JSON](results-v10.json) contains 23 completed trials: three clean
controls, two single-client pilots, nine two-client filtered comparisons,
three DNAT references, three NAT-rebinding runs and three switch-variant
screens. Independent counters saw all 6,000,000 offered noise packets.
All 5000 timed ping probes returned.

The four fresh copy-on-write guests used Debian 13 and the same patched
QEMU/WHPX build as v9. A/B/C ran Linux 6.12.116; D ran 6.12.115. Filter
binaries and source hashes were unchanged. The original C/Winsock switch
from commit `403ad7c` was used first. SHA-256 values and resources are in
the JSON. Live servers and the user's VPN were outside the experiment.

The grouped filter used the existing kernel guard: an aggregate limit of
50,000 packets/s with a 5000-packet burst, and a source-IP/UDP-port limit of
35,000 packets/s with a 3500-packet burst. No IFB or trusted-IP cache was
added. The filter continued inspecting every selected packet.

Each TCP run requested eight measured seconds after one second of warmup,
with a 5% tolerance per client. The direction cases were both clients
uploading, both downloading, and client 1 uploading while client 2
downloaded. Download uses `iperf3 -R`, as described in the
[iperf manual](https://software.es.net/iperf/invoking.html).

Noise requested 300,000 packets over twelve seconds at 25,000 packets/s:
one flow, a random 256-byte payload reused within each trial, offered
bursts of up to 4096 packets. The rate gate required the sender mean within
1%, delivery to entry within 1% and zero switch drops. Independent switch
arrival counters and 100-ms bins checked the offered packet count. An
eventual count of 300,000 does not establish that the requested rate held.

Resident collectors and fixed workload launchers avoided new SSH/sudo
sessions inside CPU windows. Their overhead remained in whole-guest CPU.
Only complete nominal 250-ms intervals between marks were analyzed;
actual intervals ranged from 230.20 to 270.35 ms. Sliding four-sample
windows sum CPU ticks. Busy CPU is user, nice, system, IRQ and softirq
divided by the first eight `/proc/stat` counters; idle, iowait and steal
remain in the denominator. Values strictly above 90% fail at the measured
resolution. This sampling does not establish an instantaneous ceiling.

## Two-client results on the original switch

Each row contains three filtered runs with a requested noise rate of
25,000 packets/s. Medians and CPU maxima include the runs that failed the
rate check; the last column identifies how many actually qualified.

| Direction | Median total Mbit/s | A max CPU % | B max CPU % | C max CPU % | D max CPU % | Rate-qualified |
|---|---:|---:|---:|---:|---:|---:|
| Both upload | 99.97 | 62.07 | 55.56 | 48.00 | 37.04 | 1/3 |
| Both download | 99.88 | 55.56 | 26.92 | 73.08 | 47.83 | 2/3 |
| Mixed | 100.03 | 59.26 | 37.93 | 62.96 | 36.36 | 0/3 |

The three rate-qualified runs recorded sender means of 24,999.82 to
24,999.83 packets/s. All three met useful-throughput, ping and CPU criteria.
The other noisy runs recorded 15,844.20 to 22,646.62 packets/s, including
pilots, DNAT references, rebinding and the switch variant. Their throughput
and CPU remain observations at those lower rates.

All twenty filtered trials, including clean controls and the switch
variant, delivered 99.87 to 100.22 Mbit/s in total. Their largest short
samples were A 62.07%, B 58.33%, C 76.92%, D 47.83%. Corresponding maxima
over sliding four-sample windows were 56.19%, 53.13%, 69.90%, 31.43%.
One client sample with the switch variant exceeded the old 75% threshold;
all filtered samples passed the new 90% threshold.

There were no NFQUEUE/netlink-user losses, client losses in the kernel
guard, shaper losses or switch drops in the completed trials. Post-guard
packets were accounted for. Invalid noise rejected by the filter is an
intended drop and is counted separately.

All three DNAT references saturated entry at 100% CPU; their total useful
rates were 9.70 to 20.01 Mbit/s. Their noise means were only 15,844 to
16,546 packets/s. These are failed references, without a matched-rate
basis for claiming a numerical speedup over DNAT at 25,000 packets/s.

## Changing an external address during active traffic

Both native clients kept their keys and profile files. Client 1 changed
from `192.168.76.30:32497` to `192.168.76.31:42501`, then returned, while
client 2 stayed at `192.168.76.30:32498`. A preinstalled rule on the lab
client VM selected the alternate SNAT address for the new runtime UDP
listen port. No profile import or reconnect was performed during the test.

Entry counters confirmed traffic on the old, new and second-client tuples
in each of three runs. Both TCP streams stayed active and delivered about
50 Mbit/s each; all 1200 timed probes in this group returned. First replies
from new ping processes arrived 62.26 to 81.79 ms after the local rebind
command. That interval includes RPC and process launch and is not a
continuous-probe outage measurement.

IP and port changed together. This does not isolate IP-only roaming or
long disconnections. Noise in these runs measured 16,595 to 20,159
packets/s, so rebinding under a sustained 25,000 packets/s remains unproven.
The result does show successful tuple changes without a static client-IP
allowlist in this lab.

## Switch experiment and measurement failures

A private `native-c-v2-eager` variant tried sending queued data without
waiting for the next writable `select()` result. Relative to the published
source, it changed only the version label and this condition:

```c
/* original */ if (p->active && p->pending && FD_ISSET(p->fd, &writes)) {
/* variant  */ if (p->active && p->pending) {
```

Nonblocking send-error handling and queue bounds were retained. The build
passed warnings as errors and the existing unit/socket tests. One screen
per direction still measured only 16,475 to 17,202 noise packets/s, so the
variant was not adopted. Published switch and filter sources are unchanged.

Switch process means in noisy original-backend runs were about 79 to 97%
of one Windows logical CPU; variant screens used about 92 to 93%. The host
has 32 logical CPUs. This is separate from the whole-VM threshold. The
observations point to limited host/backend headroom, but do not identify
which part of Winsock, QEMU or scheduling causes the rate shortfall.
Immediate send alone did not resolve it.

A controller error briefly overlapped the last primary run and the first
DNAT reference. Counter checks and the sender's bind assertion rejected
those acquisitions. A retry with a reused trace name was also refused.
The affected runs were repeated under new names after adding and checking
an exclusive controller lock. Incomplete attempts remain local and are
excluded from the 23 completed trials. Complete rate failures are retained.

## Decision and remaining scope

Retain the original native switch and grouped filter without IFB for the
next local study. First isolate noise pacing without VPN traffic, then add
forwarding and the direction cases, recording source and arrival timing at
each step. A stable offered rate is needed before capacity claims or more
packet-code optimization. Changing the CPU threshold to 90% does not fix
the pacing problem.

This study used Linux AWG clients and invalid random UDP. Physical GUI
clients, real VPS, DPI, valid-MAC1 floods and captured-prefix floods were
not tested. HPK/MAC1 remains partial filtering without client identity;
the exit still authenticates VPN traffic. The strict I1/Jc policy and its
camouflage implications are unchanged. Protocol/sanitizer suites were not
rerun for the unchanged filter.

Rollback restored ordinary DNAT, the original client NAT and runtime port.
Both native clients passed probes; client profile, filter and personal JSON
hashes were unchanged. The original helper executable was restored. All
four VMs and both helpers were stopped, and all eleven lab/self-test ports
were released. English and Russian prose was reviewed with Humanizer.
