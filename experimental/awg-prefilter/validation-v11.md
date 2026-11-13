# Fixing the Windows QEMU packet-rate bottleneck

English | [Русский](validation-v11.ru.md)

Test date: 12 November 2026. A Windows-only QEMU socket change resolved the
rate shortfall from [v10](validation-v10.md) in this series. All 33 noisy
trials on the rebuilt executable sustained the requested 25,000 packets/s:
source means were 24,999.71–24,999.84, with every offered packet counted
independently at the switch and entry. Useful TCP remained about 100 Mbit/s.

Follow-up: [v12](validation-v12.md) reproduces an early probe-exit mechanism
and adds a bounded ICMP helper. The counts below are retained; the specific
old packet has no capture for conclusive attribution.

The faster backend exposed overflow of the filter's 2048-packet queue.
Raising its bound to 4096 removed recorded queue losses in twelve final
repeats. One ping still went unanswered in those repeats, so this is not
a loss-free qualification of the entire path.

## Cause and controlled comparison

QEMU 11.1.3's `net/socket.c:net_socket_receive` passes a four-byte length
and Ethernet payload to `iov_send`. The non-POSIX fallback in `util/iov.c`
sends these pieces separately. With `TCP_NODELAY`, a prefix can reach the
receiver before its frame, adding socket operations and wakeups. Scheduling
and TCP coalescing make that cost variable. The v10 immediate-send switch
experiment did not change these upstream writes.

The [patch](lab-switch/qemu-win32-single-write.patch) builds one contiguous
prefix/frame buffer for a Windows `send()` attempt. Existing partial-write
offsets and error handling remain in use; the POSIX branch is unchanged.
One send still need not equal one TCP segment or one receive. The native
switch's framing, FIFO queues and source are unchanged.

Four disposable Debian 13 guests each had 1 vCPU and 1024 MiB RAM, with
the same kernels, AWG keys, noise generator, guard and C/Winsock switch as
v10. The QEMU sequence was original, patched, reverted, then patched for
confirmation. All three noise-only runs before the patch missed the rate;
one of three reverted runs missed it again. The old build can sometimes
reach the target, as earlier studies also showed.

| Noise-only phase | Source packets/s range | Rate-qualified | Switch mean CPU %, one host logical CPU |
|---|---:|---:|---:|
| Original | 19,766–22,817 | 0/3 | 86.13–88.84 |
| Patched | 24,999.71–24,999.82 | 3/3 | 41.63–68.22 |
| Reverted | 23,224–24,999.82 | 2/3 | 71.21–75.70 |

The [regression test](lab-switch/test_qemu_stream.py) compiles the actual
QEMU send function against fake I/O. The original fails the one-write
assertion; the patched function passes exact framing, partial retries,
`EAGAIN`, zero writes, fatal errors, zero/maximum payload and cleanup checks.
The incremental QEMU build also passed. These results support the extra
Windows writes as the tested bottleneck; host scheduling can still affect
performance under other loads. [Build and test instructions](lab-switch/README.md).

## Workload and CPU measurements

The [JSON](results-v11.json) records 45 completed trials: nine runs without
useful TCP, six direction screens, two nine-run filtered matrices, six
rebinding runs, three clean controls and three DNAT references. Forty-two
trials used noise; 33 used the patched executable. All 12,600,000 offered
noise packets were independently counted. Timed pings returned 8398 of
8400 replies across the whole series. Failed controls and losses remain
in the data.

Noise settings were unchanged: 300,000 UDP packets targeting twelve seconds
at 25,000/s, one flow, one random 256-byte payload reused within each trial,
offered bursts up to 4096. The rate gate checks the sender mean within 1%,
delivery to entry within 1% and zero switch drops. This is repeatability of
a burst workload over twelve seconds, not a flat instantaneous packet rate.
Source burst records and independent 100-ms arrival bins were retained.

Two independent native AWG clients requested 50 Mbit/s each: both uploading,
both downloading, or client 1 uploading while client 2 downloaded. Runs had
one second of warmup and eight measured seconds, with 5% tolerance per
client. The grouped filter kept the existing 50k/5000 aggregate and
35k/3500 source-IP/UDP-port guard. No IFB or trusted-IP cache was added.

The CPU threshold was 90% of each whole VM, without quotas. Resident
collectors and fixed workload launchers stayed in the measured budget;
no new SSH/sudo sessions were created inside the windows. Only complete
nominal 250-ms marked intervals were analyzed, actually 242.82–257.03 ms.
Four-sample windows sum ticks. Busy is user+nice+system+IRQ+softirq divided
by the first eight `/proc/stat` counters, retaining idle/iowait/steal in
the denominator. Every completed trial stayed below 90% at both resolutions.
This sampling does not establish an instantaneous CPU ceiling.

## Queue correction and final repeats

After the QEMU fix, trials with the old queue recorded 7240 NFQUEUE
overflow drops in total. Their packet origins cannot be identified from
that aggregate counter. One ping was missing in the first primary matrix.
Faster delivery changed burst timing even though the offered workload
remained the same.

The filter now uses a shared `QUEUE_MAXLEN=4096` constant for configuration
and startup reporting. Only that bound and its telemetry changed; crypto
checks, copied length, individual verdict IDs, fail-closed behavior, guard
and receive-buffer reservation are unchanged. The queue remains finite and
uses kernel memory; larger bursts or a stalled consumer can still overflow.
The ordinary/grouped protocol and verdict suites passed with
`make check check-batch` on the entry VM.

The final matrix used three rotated/reversed repeats per direction, with
the patched QEMU and 4096-packet queue. Every run met rate, per-client
throughput and whole-VM CPU targets and had zero queue/guard/shaper/switch
losses. The strict pass column also requires every ping to return.

| Direction | Median total Mbit/s | A max CPU % | B max CPU % | C max CPU % | D max CPU % | Strict pass |
|---|---:|---:|---:|---:|---:|---:|
| Both upload | 100.10 | 48.15 | 25.93 | 21.43 | 14.81 | 3/3 |
| Both download | 100.01 | 46.43 | 19.23 | 34.62 | 17.86 | 3/3 |
| Mixed | 99.99 | 46.43 | 22.22 | 23.08 | 15.38 | 2/3 |

The mixed failure had one missing ping, without an entry queue, guard,
shaper or switch drop. Its cause is not localized. TCP throughput and CPU
passed, but the strict loss-free criterion did not. Increasing the queue
again would not address any demonstrated overflow in that run.

Three further rebinding repeats used the same final build and verified
25,000 noise packets/s. Client 1 changed external IP and port together and
returned; client 2's tuple stayed unchanged. Both TCP streams survived,
all 1200 timed probes returned and entry counters saw every tuple. Keys
and profile files were unchanged. First replies from newly launched probes
arrived 76.72–103.10 ms after the local command; that includes RPC/process
launch and does not measure a continuous-probe outage.

Across these twelve final runs, total TCP was 99.99–100.14 Mbit/s; CPU peaks
were A 48.15%, B 25.93%, C 34.62%, D 18.52%. No NFQUEUE or netlink-user
losses were recorded; pings returned 2999/3000. All twelve met rate,
throughput and CPU targets; eleven met the stricter combined criterion.

## What changes in the conclusions

Ordinary DNAT also passed the three patched-backend references: about
100 Mbit/s, verified 25,000 noise packets/s, all pings returned and entry
peaks of 54.17–63.64%. Earlier DNAT saturation was backend-dependent.
Those historical measurements remain observations of their setups and
cannot establish an intrinsic speed advantage for the filter. This stage
has one DNAT repeat per direction, so it is not a statistical speed ranking.

Keep the QEMU patch and bounded 4096-packet queue for this lab. The rate
shortfall is resolved in the tested series; one unexplained ping loss
still prevents a blanket loss-free claim. Installers continue using
ordinary DNAT. HPK/MAC1 remains partial filtering, without client identity;
the exit authenticates VPN traffic. Strict I1/Jc handling is unchanged.

No physical GUI clients, real VPS, DPI, valid-MAC1 floods or captured-prefix
floods were tested. The changed queue received protocol/batch tests and
live burst tests; sanitizers were not rerun for the constant-only change.
The earlier WHPX compatibility patch was retained, not changed by this fix.

Rollback restored ordinary DNAT, client NAT and runtime port; both clients
passed probes. Client profile and personal JSON hashes were unchanged.
The final filter binaries match the queue-4096 build hashes. All four VMs
and both helpers were stopped, and all eleven lab/self-test ports released.
Live servers, the user's VPN, WSL configuration and Windows networking
were untouched. English and Russian prose was reviewed with Humanizer.
