# NFQUEUE costs and profiling overhead

English | [Русский](validation-v6.ru.md)

Test date: 12 November 2026. At the same requested upload rate and noise,
IFB reduced verdict grouping and increased worker CPU. Fine-grained timing
also changed grouping, so its component percentages cannot describe the
ordinary build directly. Grouping loss explains part of the IFB penalty;
the remaining mechanism has not been isolated. Filter code and installers
are unchanged.

[results-v6.json](results-v6.json) records 36 traffic trials, four build
checks totalling 78 tests, and three clock-read calibrations.
The [previous report](validation-v5.md) covers smoothing and fragmentation.

## Method

Four new copy-on-write VMs each had 1 vCPU and 1024 MiB RAM. QEMU/WHPX and
the localhost switch with `TCP_NODELAY` were retained. Entry, exit and client
used Debian 13/Linux 6.12.116; the noise source used Linux 6.12.115.
Bootstrap metadata paths were corrected before testing. A client clone
required direct boot of its installed kernel image with `cloud-init=disabled`;
the image hash was verified. Bootstrap retries produced no performance data.
See [cloud-init's documented switch](https://docs.cloud-init.io/en/latest/howto/disable_cloud_init.html).

The ordinary individual/grouped binaries were reused and hash-verified.
The unchanged source was compiled with `PREFILTER_PROFILE`, with and without
`PREFILTER_BATCH`. All four optimized configurations passed their 16/23
protocol and verdict tests. ASan was not rerun in this stage.

TCP measured eight seconds after a one-second warmup at a requested
100 Mbit/s, with 5% tolerance. Noise offered 10000 packets/s for twelve
seconds, beginning about a second before TCP. The full counter/CPU interval
includes the noise before and after TCP and quiescent collection overhead.
It differs from v5's TCP-window CPU measurements.

There were two pilots, twelve noisy grouped-build comparisons, eight clean
controls, six individual-build references and eight noise-only cases.
The primary noisy comparison used three repetitions with rotated/reversed
order; clean controls had two. Noise-only cases had one run per combination
of policy, build and offered burst of 20 or 4096 packets. No arrival trace
was captured for those patterns, so they do not establish a uniform ingress rate.

Ingress was gated and queues drained before stable snapshots. All 36 cases
had exact post-guard accounting and no switch or netlink-user drops. Nine
cases had NFQUEUE drops; these remain in the results. All primary noisy
cases met the rate target. Two clean profiled IFB cases delivered 83.23 and
24.51 Mbit/s; a profiled individual case delivered 92.84 Mbit/s. They are
excluded from matched-rate comparisons. The clean failures coincided with
high guest iowait, reaching 80.67% on the exit in the latter case; their cause
was not isolated. Overall, 2763 of 2800 timed pings received replies.

## Ordinary builds

These are medians of three primary noisy runs. Worker CPU is a percentage
of one core over the full snapshot interval. It is not whole-VM CPU.

| Policy/build | Delivered Mbit/s | Worker CPU % | CPU time per inspected packet, us | Verdicts per submission | Voluntary switches per 1000 packets |
|---|---:|---:|---:|---:|---:|
| Baseline, grouped | 100.05 | 8.22 | 5.07 | 14.26 | 14.84 |
| IFB 1 MiB, grouped | 100.05 | 22.56 | 13.92 | 4.91 | 60.00 |
| Baseline, profiled grouped | 100.06 | 17.00 | 10.59 | 14.68 | 10.67 |
| IFB 1 MiB, profiled grouped | 101.10 | 28.72 | 17.74 | 8.58 | 20.44 |

In the ordinary build, IFB required about 2.7 times the worker CPU time per
inspected packet and about four times as many voluntary switches per packet.
The individual-submission reference without IFB used 15.66% worker CPU and
9.72 us per packet. That is below the grouped IFB variant despite submitting
one verdict per call. Smaller groups alone therefore do not explain the
whole cost difference. Cache, wakeup and forwarding contributions were not
separately measured.

The profiler itself changed the IFB workload: verdicts per submission rose
from 4.91 to 8.58, while voluntary switches fell from 60.00 to 20.44 per
1000 packets. Subtracting one fixed instrumentation cost would miss this
change in execution pattern.

## Timed components

Values below are cumulative CPU nanoseconds divided by inspected packets
across the three profiled runs, expressed in microseconds. They are weighted
aggregates, unlike the medians above, and include timing overhead.

| Profiled policy | Receive | Inspection | Verdict submission | Unattributed worker time |
|---|---:|---:|---:|---:|
| Baseline | 1.180 | 4.258 | 3.198 | 1.611 |
| IFB 1 MiB | 1.810 | 6.437 | 6.448 | 2.531 |

Header decoding and handshake MAC1 timing are nested inside inspection;
they must not be added again. Grouped verdict timing surrounds submission,
with encoding outside it. Individual timing surrounds the library call and
includes its encoding, so those fields are not equivalent across builds.
Unattributed time includes work outside the measured regions; it is not a
kernel-only category.

Total worker runtime came from the first field of
[`/proc/PID/schedstat`](https://docs.kernel.org/scheduler/sched-stats.html).
The process was verified single-threaded. Its runtime was cross-checked
against user/system ticks; the maximum difference was 13.82 ms.
`kernel.sched_schedstats` was disabled, so runqueue-wait fields were not used.
Context-switch counts came from `/proc/PID/status`.

A separate million-read loop cost 663.875, 664.338 and 691.579 CPU ns per
thread-clock read, including loop/assert overhead. It ran without workload.
No such estimate was subtracted from the profiles or treated as the clock
cost under live traffic. The timers are useful diagnostics, not pure cipher
benchmarks or an attribution of ordinary-build CPU shares.

## The 75% whole-VM criterion

After collection, 75% CPU per guest was set as an acceptable-load criterion,
without imposing a CPU quota. Auditing the 36 traffic-trial whole-guest windows gave
maxima of 56.88% for entry, 18.29% for exit and 19.09% for client. CPU alone
does not require optimization at these tested loads under that criterion.

These are window averages. Short peaks and the noise VM's CPU were not
recorded, so this does not establish that all four VMs remain below 75%
at every instant or at higher offered loads. The worker percentages in the
first table must not be compared directly with the whole-guest threshold.
The separate clock calibration was a CPU-bound loop and is outside this
traffic-window audit; its worker CPU/wall ratios are included in the JSON.

## Decision

Keep the ordinary grouped build available for experiments. Keep IFB out of
the default setup because the earlier traffic-loss and fragment-selection
limits remain. Its higher measured CPU is within the new average-load
criterion here and is not, by itself, grounds for rejecting it.

Before changing packet-processing code, use lower-impact sampling and
record whole-guest CPU, including the noise source and shorter intervals.
This study does not justify weakening HPK/MAC1 checks or adding trusted-IP
caches. No new rate preset, kernel crypto path or production deployment was made.
Physical GUI clients, real VPS, DPI resistance and maximum flood capacity
remain untested. The four VMs/helpers were stopped, the original binary
slots restored, and all ten localhost ports released.
