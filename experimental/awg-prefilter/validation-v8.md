# Resident measurements and the lab switch limit

English | [Русский](validation-v8.ru.md)

Test date: 12 November 2026. Repeated SSH collection reproduced short CPU
peaks on the noise VM. Launching measurements and workloads through resident
processes removed those peaks from the filtered controls. At a verified
15,000 noise packets/s and 100 Mbit/s upload, all six filtered controls met
the 75% criterion on all four guests. Requested 25,000-packet/s trials
failed the pacing check because the lab path could not sustain that rate.

The [JSON](results-v8.json) summarizes 34 trials, including all 16 failed
25,000-packet/s attempts. Full traces remain local. Filter source, ordinary
binaries, admission checks and production installers are unchanged.

## What changed in measurement

Four new copy-on-write VMs each had 1 vCPU and 1024 MiB RAM. Debian kernels,
ordinary filter binaries and the QEMU/WHPX build were retained from
[v7](validation-v7.md). Entry, exit and client used Linux 6.12.116, the noise
source 6.12.115. No CPU quotas were set.

A resident process per guest sampled whole-VM CPU at nominal 250-ms
intervals and accepted before/after marks over an already open SSH stream.
The detailed mode also read process counters, matching PID and start time
to avoid PID-reuse errors. Short-lived tasks can disappear between reads;
exec and asynchronous reads also limit attribution. The observed process
deltas are incomplete and must not be treated as exact CPU shares. See
[/proc/PID/stat](https://man7.org/linux/man-pages/man5/proc_pid_stat.5.html).

The first clean control used about 13 to 15 ms of sampling-process CPU per
trace. Detailed controls used roughly 0.3 to 0.35 seconds, excluding startup
and final JSON encoding. This extra cost remains in the guest measurements.
One clean pair is not an overhead benchmark for every workload.

Later trials also launched the fixed lab noise, iperf and ping commands
through the resident process. They needed no new SSH authentication or sudo
invocation inside the measurement window. The command handler accepts only
those workloads, fixed private destinations and bounded rates. The existing
shell-based snapshot remained available as a deliberate tail intervention.

CPU selection used complete intervals between resident marks, covering TCP
warmup, eight measured seconds, a two-second tail, and late noise completion
where necessary. Busy CPU includes user, nice, system, IRQ and softirq time.
Idle, iowait and steal stay in the denominator. Sliding four-sample windows
sum ticks. A value strictly above 75% fails at the measured resolution;
these data do not establish an instantaneous ceiling. Actual intervals
across all series were 234.49 to 269.43 ms.

## Matched 15,000-packet/s comparison

Each row has three repetitions, with rotated/reversed order. All twelve
trials met the sender-rate and delivery checks. `baseline` means the ordinary
grouped filter plus the unchanged kernel guard. `ifb1024` adds the previous
200-Mbit/s TBF with a 1-MiB limit. `+ SSH` deliberately launches the older
snapshot helper during the two-second tail. Table CPU values are maxima
over nominal 250-ms samples, including collection overhead.

| Policy | Median Mbit/s | A max CPU % | B max CPU % | C max CPU % | D max CPU % | Rate, throughput and CPU passed |
|---|---:|---:|---:|---:|---:|---:|
| dnat | 29.65 | 100.00 | 46.43 | 100.00 | 22.73 | 0/3 |
| baseline | 100.04 | 54.17 | 48.28 | 36.00 | 19.23 | 3/3 |
| baseline + SSH | 100.05 | 68.00 | 48.00 | 45.83 | 100.00 | 0/3 |
| ifb1024 | 100.04 | 69.23 | 53.57 | 40.74 | 29.17 | 3/3 |

Without the injected snapshot, the baseline noise-source maxima were
18.52, 19.23 and 18.52%. With the snapshot, they became 81.25, 100 and 100%.
The sender itself used about half a second of system CPU over twelve
seconds in both groups. Earlier diagnostic hot samples contained active
`sshd-session`, `sshd-auth` and `sudo` processes, while the noise sender
showed little CPU activity. Examples are included in the JSON.

This reproduces an observer-generated failure of the short-window criterion.
It supports that explanation for the reproduced peaks; it does not assign
every spike from older studies retrospectively. Measurements remain part
of total guest load, so the injected cases retain their failed CPU result.

All six filtered controls preserved about 100 Mbit/s and stayed below 75%
on every guest. DNAT saturated entry and delivered 28.73 to 32.57 Mbit/s in
this series. One DNAT trial also had hot client samples. These are results
for this lab's packet timing and virtual I/O, not a VPS capacity estimate.

## Why the requested 25,000 packets/s were not verified

The pilot observer also saw unrelated source UDP outside its trial windows.
Before the main series it was restricted to the exact lab flow. Guests
were restarted for that correction and for the later switch candidate;
temporary client namespaces were recreated before measurements.

Windows host sampling recorded QEMU and switch process times alongside
guest measurements. Host utilization covers 32 logical CPUs; process
percentages use one logical CPU as their reference. The methods use
[GetSystemTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getsystemtimes)
and [GetProcessTimes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-getprocesstimes). These percentages have a different denominator from
whole-guest CPU and are not subject to the guest's 75% acceptance rule.

In the twelve initial requested-25k diagnostics, the Python switch averaged
about 99 to 100% of one host logical CPU. The sender's actual mean stayed
around 19,000 to 20,000 packets/s. Independent switch arrival timestamps
agreed with the lower rate, and counters saw every sent packet. In one
representative run, sending loops occupied 14.997 of 14.998 wall seconds,
but the sender used only about 0.857 seconds of system CPU. Sender CPU was
read with [getrusage](https://man7.org/linux/man-pages/man2/getrusage.2.html).

A lab-only switch candidate changed selector registration only when an
output queue became nonempty, and compacted its receive buffer once per read. Its framing, split/coalesced reads, unicast order/isolation,
oversized-frame disconnect and exact noise counting passed socket tests.
The higher requested rate still failed: two checks reached about 17,600
to 17,700 packets/s. Two checks with persistent workload launches reached
about 17,500 to 18,000. Switch CPU remained near one core. The candidate
did not remove the limitation; boot/timing changes also prevent assigning
the rate difference to either small optimization alone.

The switch counters use monotonic arrival times before forwarding and
100-ms bins. The first-to-last rate excludes the sender's final pacing
sleep, so it can differ slightly from its full-run mean. Mean rates do not
establish identical burst patterns across series. Zero switch drops or
blocked writes also cannot rule out backpressure inside QEMU or on the
switch's input side. The evidence points to a lab I/O/scheduling limit,
without isolating every queue or wait source.

The final comparison therefore used a verified 15,000 packets/s. Its switch
still averaged about 89 to 96% of one host logical CPU. A faster validated
network backend is needed before using this setup to estimate capacity at
higher rates. The old v7 numbers remain observations from that environment;
absolute capacity comparisons between these stages are not justified.

## Checks and decision

All 34 trials had exact post-guard accounting where the filter was active,
no switch/NFQUEUE/netlink-user/shaper/guard drops, and complete independent
arrival counts. All 3400 timed pings received replies. Eighteen trials,
including three clean controls, passed workload-quality checks. The sixteen
failed pacing attempts remain diagnostics and are excluded from matched
25,000-packet/s claims.

The resident CPU/parser/PID-reuse checks, bounded job-command checks,
Windows CPU API check, exact-flow selector checks and real socket-switch
tests passed. The observed sender compiled with warnings as errors; all
recorded burst traces passed count and timing consistency checks. Both
native clients worked after rollback. The unchanged filter's protocol and
sanitizer suites were not rerun in this stage.

Keep the grouped filter experimental. Further packet-code optimization
should follow a faster lab backend and a fresh arrival/pacing check.
The measurements do not justify weakening HPK/MAC1 or adding trusted-IP
caches. IFB stays outside default installation because earlier useful-packet
loss and fragment-selection limitations remain unresolved. No physical GUI
clients, real VPS, DPI resistance or maximum flood capacity were tested.

DNAT was restored, source/binary and personal JSON hashes were unchanged,
all four VMs and both helpers were stopped, and all lab/self-test ports were
released. Live servers and the user's VPN were untouched. HPK/MAC1 remains partial filtering without client authentication.
