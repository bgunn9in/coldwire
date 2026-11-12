# Short-window CPU and lower-impact sampling

English | [Русский](validation-v7.ru.md)

Test date: 12 November 2026. At 100 Mbit/s useful upload and 10,000 noise
packets/s, all four lab VMs stayed below 75% CPU in the measured intervals.
At 25,000 packets/s, ordinary DNAT saturated entry softirq processing.
The filter preserved useful throughput in that comparison, but the noise
source exceeded 75%, so the whole four-VM setup did not pass at that rate.

The [JSON](results-v7.json) contains 25 rate-qualified trials and four
additional sender diagnostics that failed the requested-rate check.
Filter code, binaries and production installers are unchanged.

## Method and checks

Each disposable copy-on-write VM had 1 vCPU and 1024 MiB RAM. A, B and C
used Debian 13/Linux 6.12.116; D used Linux 6.12.115. A, B and C booted their
installed kernel directly with cloud-init disabled. QEMU/WHPX used the
localhost Ethernet switch with `TCP_NODELAY`. Entry used OpenSSL 3.5.7,
glibc 2.41 and libnetfilter_queue 1.0.5. Installing `linux-perf` changed the
lab's tool packages; versions and library hashes are recorded in the JSON.
Absolute CPU figures from older studies are not directly comparable.

The two ordinary binaries were reused and hash-verified. No new filter
build or protocol-test run was needed. Synthetic CPU calculations, weighted
windows, the perf parser against a real report, and Python syntax checks
passed. An early parser assumed five columns; perf sometimes adds IPC.
That parser was corrected before the analyzed series. Initial pilot
artifacts and two aborted sender checks remain private and are excluded
from the 29 complete analyzed trials.

TCP ran for eight measured seconds after one second of warmup, requesting
100 Mbit/s with 5% tolerance. D targeted twelve seconds of one flow of
random 256-byte UDP payloads, in bursts of up to 4096 packets. Each trial
reused one payload. Burst duration varied; the mean rate alone does not
describe the arrival pattern. The filter modes used the existing kernel
guard. IFB added TBF at 200 Mbit/s with a 64 KiB burst and 1 MiB limit.
DNAT had neither experimental guard nor filter.

All 29 analyzed cases had no switch, NFQUEUE, netlink-user, shaper or guard
drops, exact post-guard accounting where the filter was active, and at
least 99% delivery of offered noise to entry. All 2900 timed pings returned.
Two DNAT cases missed the TCP target. The four sender diagnostics also
missed the requested noise rate and are kept outside matched-rate comparisons.

## Whole-VM CPU

75% remains an acceptance criterion for each entire VM. No CPU quota was
set. A small resident sampler read `/proc/stat` every nominal 250 ms.
Busy CPU includes user, nice, system, IRQ and softirq time; idle, iowait
and steal are excluded from the numerator. Only complete intervals inside
each guest's before/after TCP snapshot window were analyzed. These windows
include warmup and management overhead; they are not the full noise run.

The four-sample windows sum ticks over four consecutive samples. They are
roughly one second long, with actual durations retained. They do not average
the percentages of unequal intervals. A sample strictly above 75% fails
the criterion at that resolution. This cannot establish an instantaneous
CPU ceiling or account for host contention that the guest does not report.

The main series had three repetitions of each policy/control combination,
with rotated/reversed order. Its maximum CPU values were:

| VM | Max nominal 250 ms CPU % | Max four-sample CPU % |
|---|---:|---:|
| A | 66.67 | 46.74 |
| B | 55.56 | 51.96 |
| C | 53.85 | 28.71 |
| D | 50.00 | 12.63 |

No main-series window exceeded 75%. Actual sample durations were
244.17 to 255.82 ms. The sampling loop and signal handling used at most
16.99 ms of process CPU per trace in that series, excluding startup and
final JSON encoding. Other collection and SSH overhead is
included in whole-VM CPU and was not separately attributed.

## Sampling the ordinary grouped binary

Two corrected pilots checked collection, followed by the 15-trial main
series. Software `cpu-clock` sampling requested 199 Hz on the filter PID,
using the monotonic clock. Reports selected entry's TCP snapshot window.
There were no lost perf records in the analyzed profiles. The
[perf record](https://man7.org/linux/man-pages/man1/perf-record.1.html) and
[perf report](https://man7.org/linux/man-pages/man1/perf-report.1.html)
manuals describe the collection and time selection.

Each row below is the median of three runs at 10,000 noise packets/s.
Worker CPU covers the longer quiescent snapshot interval, including noise
before and after TCP; it must not be compared with the whole-VM peaks above.

| Policy, sampling | Mbit/s | Worker CPU % | CPU us/inspected packet | Verdicts/submission |
|---|---:|---:|---:|---:|
| baseline, control | 100.09 | 11.70 | 7.25 | 4.99 |
| ifb1024, control | 100.10 | 12.46 | 7.71 | 4.45 |
| baseline, perf | 100.10 | 11.96 | 7.38 | 4.63 |
| ifb1024, perf | 100.09 | 13.12 | 8.09 | 4.33 |

Sampling increased median worker time per packet by about 2% without IFB
and 5% with IFB. Grouping also shifted. Three repeats cannot separate this
small change from run-to-run variation; the data do not support assuming
zero observer effect.

Without per-packet timers, the large IFB penalty from
[v6](validation-v6.md) did not repeat here: control medians were 7.25 and
7.71 us per packet. Grouping was already about five verdicts per submission
without IFB. This series does not isolate why the older baseline grouped
more packets, or invalidate the earlier recorded measurements.

The three sampled baseline runs contained 742 samples; IFB had 881.
Weighted by recorded sample periods, kernel code accounted for about 79%
in both, and libcrypto for about 11% and 12%. These are sampled instruction
locations in the worker's context, not independent component benchmarks.

Two additional frame-pointer stack trials confirmed a verdict path:

```text
netlink_sendmsg -> nfqnl_recv_verdict -> nfqnl_reinject
  -> ip_output -> dev_hard_start_xmit -> virtqueue_notify -> iowrite16
```

132 of 254 baseline stack samples and 132 of 286 IFB samples contained an
NFQUEUE reinjection/verdict frame. Virtio frames appeared in 32 and 51.
These counts overlap. The stacks show that worker-context time can include
forwarding and virtual NIC notification after a verdict. Userspace unwind
was often unresolved. This does not measure the physical NIC cost on a VPS.

## Higher offered load and sender diagnostics

The six unprofiled escalation trials requested 25,000 packets/s; all met
the sender-rate and delivery checks. Both DNAT trials saturated entry,
mostly in softirq, and delivered 54.58 and 74.35 Mbit/s. Their ping p99 was
371 and 146 ms. Filtered cases delivered about 100 Mbit/s.

| Policy | Repeat | Mbit/s | Entry mean CPU % | Entry max sample % | D max sample % |
|---|---:|---:|---:|---:|---:|
| dnat | 1 | 54.58 | 95.31 | 100.00 | 100.00 |
| baseline | 1 | 100.07 | 45.30 | 66.67 | 100.00 |
| ifb1024 | 1 | 100.07 | 46.74 | 62.96 | 100.00 |
| ifb1024 | 2 | 100.10 | 46.30 | 53.57 | 50.00 |
| baseline | 2 | 100.08 | 42.90 | 50.00 | 95.24 |
| dnat | 2 | 74.35 | 94.04 | 100.00 | 100.00 |

The baseline/IFB entry samples stayed below 75% in these six trials.
D exceeded 75% in five trials, including both baseline repeats. Exit also
had one 84% sample under DNAT. Actual sample durations in this series were
234.15 to 264.48 ms. The four-VM acceptance criterion therefore failed.
These cases establish neither a universal 25,000-packet/s limit nor maximum
filter capacity.

A lab-only follow-up compared two original UDP senders with two senders
that connected each socket to the fixed lab destination before `sendmmsg`.
The source address/port, payload size and burst limit stayed the same.
All four failed the requested 25,000-packet/s rate, reaching only
18,688 to 19,893 packets/s. Connected runs used 0.779 and 0.781 seconds of
sender system CPU; originals used 0.882 and 0.899. Entry and D still had
samples above 75%. The result does not validate this optimization at the
target workload. Sender timing changed, so it is not a controlled arrival
pattern comparison either.

D's peaks in the rate-qualified escalation clustered near the end of its
snapshot windows. Collection overhead and virtualization need attribution
before changing the sender or filter. The cause was not isolated, and the
failed windows remain in the results.

## Decision and next experiment

Keep the grouped filter in the lab and retain the existing authentication
checks. The next useful step is a resident collector that attributes short
peaks to processes and kernel work without repeatedly launching helpers,
followed by an independent check of sender pacing and host/socket-link
backpressure. Only then repeat the higher-load comparison and choose a CPU
optimization. The measured reinjection path does not justify weakening
HPK/MAC1 or adding a trusted-IP cache.

IFB stays outside the default setup: earlier useful-packet loss and the
fragment-selection gap remain unresolved. This stage did not retest GUI
clients, physical VPS, DPI resistance or maximum flood capacity. HPK/MAC1
still provides partial filtering, not client identity; replay and captured
transport-prefix limitations remain.

Rollback restored DNAT and both native client probes passed. Original
binary/source hashes and personal JSON were unchanged. All four VMs and
both helpers were stopped; all ten localhost ports were released. Live
servers and the user's VPN were untouched.
