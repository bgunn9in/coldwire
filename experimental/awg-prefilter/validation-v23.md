# Where return recovery stops covering a NAT move

English | [Русский](validation-v23.ru.md)

Test date: 14 November 2026. The 500-ms recovery build from [v22](validation-v22.md)
reduced loss at larger RTTs but did not make roaming lossless. At RTT 600 ms,
the recovery trial lost 413 UDP datagrams; its disabled control lost 4153.
At 1000 ms the counts were 3081 and 4805. Two moves 250 ms apart lost 3658,
while the 1200-ms interval delivered every datagram in its trial.
See [results and evidence hashes](results-v23.json).

Recovery remains off by default and separate from the VPS installers.
Production servers and the user's VPN were not accessed. CPU has no
acceptance threshold or quota in this stage.

## Workload and accounting

Four fresh COW guests used Debian 13, kernel 6.12.116, QEMU 11.1.3/WHPX,
one vCPU and 1024 MiB each. A is the entry, B the exit, C the client gateway,
and D the noise source. The stopped v22 disks were backing files and were
checked unchanged after shutdown. Both native AWG client binaries,
profiles, keys and listen ports stayed unchanged. C changed only its NAT
mapping, without a fixed client-IP allowlist.

Each of the eleven counted trials offered 25,000 noise datagrams/s for
70 seconds from one address and 64 ports, in 4096-datagram bursts. Noise
used a captured transport prefix with altered ciphertext. Useful reverse
UDP requested 6000 or 24,000 application datagrams/s, with 128-byte payloads,
for 60 seconds. All runs used v22's separate iperf3 3.18 startup-reorder
benchmark. The VPN clients were not modified.

Netem delayed each A-B direction by half the requested RTT, including the
mutual-TLS control channel, with normal jitter of 10% of RTT per direction.
Both queues held 16,384 packets and had no configured loss. Management
and D-to-A noise had no added delay. Twenty physical pings checked each
requested RTT before load. The gateway changed the first mapping 25 seconds
after workload launch. A second move used the original IP with another NAT
port; its interval starts after the first conntrack deletion completes.

Complete buffered inner UDP captures count unique datagrams at B and C.
The parser handles GSO/GRO and the short startup-control tail described in
v22. The source capture agrees with iperf's sent count. Iperf's loss estimate
is retained separately because reordering and startup accounting can make
it disagree with tunnel delivery. Captures do not prove application consumption.
The counted 24,000/s pair uses a 32-MiB UDP capture buffer and a 128-MiB
capture-process memory ceiling, within the same 1024-MiB guest. Other trials
use 4 MiB and 32 MiB. This is measurement overhead, not a VPN cache change.

Each native profile also sent 100 probes at nominal 500-ms intervals.
Profile 1 sent another 100 at 50-ms intervals around the move. The deadline
remained one second. In the table, "late" counts replies read after that
deadline; "captured" counts all unique replies at the client tunnel,
including those arriving after the probe stopped reading. At RTT near
one second, ordinary path delay alone can exceed the deadline.

## Completed traffic trials

Recovery is enabled except where marked off. Jitter is per direction.
CPU is the largest stored nominal 250-ms whole-VM sample across all roles.

| Scenario | RTT / jitter ms | UDP/s | UDP sent | UDP missing | Frequent: timely / late / captured | Peak CPU % |
|---|---|---|---|---|---|---|
| Port only, recovery on | 300 / 30 | 6000 | 362146 | 0 | 100 / 0 / 100 | 86.96 |
| IP + port, on | 600 / 60 | 6000 | 363452 | 413 | 97 / 3 / 100 | 80.00 |
| IP + port, off | 600 / 60 | 6000 | 364901 | 4153 | 88 / 0 / 88 | 68.18 |
| IP + port, on | 1000 / 100 | 6000 | 366130 | 3081 | 41 / 46 / 90 | 76.92 |
| IP + port, off | 1000 / 100 | 6000 | 365596 | 4805 | 37 / 46 / 84 | 76.92 |
| Two moves, 250 ms | 300 / 30 | 6000 | 362087 | 3658 | 88 / 0 / 88 | 74.19 |
| Two moves, 1200 ms | 300 / 30 | 6000 | 362150 | 0 | 100 / 0 / 100 | 71.43 |
| Outbound pause 300 ms | 300 / 30 | 6000 | 361875 | 887 | 92 / 0 / 92 | 80.00 |
| Outbound pause 750 ms | 300 / 30 | 6000 | 361895 | 3644 | 79 / 0 / 79 | 68.18 |
| High PPS, off | 300 / 30 | 24000 | 1447661 | 321629 | 81 / 0 / 81 | 100.00 |
| High PPS, on | 300 / 30 | 24000 | 1450157 | 553833 | 63 / 0 / 63 | 100.00 |

These are single observations per case. Requested seeds match where the
settings match, but scheduling and packet timing differ. The comparisons
do not provide a confidence interval or a universal RTT cutoff.

The two pause trials deliberately dropped profile 1's outbound encrypted
UDP at the gateway for 300 or 750 ms after changing NAT. The counters were
6 and 18 packets. This delays discovery of the
new endpoint and also removes probe requests, which return recovery cannot
restore. The data separates requests missing at B from replies missing at C.

All counted trials qualified their noise rate. The total was
19,250,000 offered noise datagrams. Client/control guard,
NFQUEUE/netlink, netem qdisc, switch and capture drops were zero; noise received
no lease. No plaintext duplicates were observed. Useful source rate was
within 1% of its requested value in 11/11 trials.
Peak CPU by role was entry 86.96%, exit 100.00%, client 100.00%, attacker 30.77%.
B's AWG RSS high-water mark was 112.03 MiB with the
stock 96-MiB Go soft memory limit. No guest logged an OOM or replay-send error.

At 24,000/s, missing datagrams were spread across most of the run, not just
the NAT move. With recovery off/on, B's `awg0` TX-drop counter grew by
314,620/553,776; missing UDP counts were 321,629/553,833. The interface counter
also includes other tunnel traffic, so these are not a one-to-one loss
equation. The client namespace recorded 20,330/10,237 UDP receive-buffer
errors, separately from tunnel delivery. These runs expose saturation of
the one-core path with full capture; they do not isolate the cache's
steady-state cost or the 4096-packet recovery limit. Other interface and
protocol deltas, including IFB counters, remain in the data.

## What limits coverage

The Go runtime binary is unchanged from v22, SHA-256
`19b0b187bff038172d5817abbc11fb244b6f7a3336e94679e736c4b83715ed01`.
It caches at most 8192 encrypted replies and 8 MiB globally. Eligibility
ends at age 500 ms. A recovery selects the newest matching suffix, at most
4096 packets and 2 MiB, then sends it in increasing order. Other peers can
evict a client's replies from the shared cache.

The age starts when B remembers the ciphertext, before reading its send
endpoint. Packets already in flight when NAT changes can be lost too.
From the path layout and code, the oldest needed reply can therefore be
roughly one RTT plus the wait for a new client packet old, with queueing
and jitter adding to it. This is an interpretation of the measured loss
and source, not a traced timestamp for every replay attempt.

A peer may attempt recovery only once per second, including an empty
lookup. There is also a 250-ms global nonempty spacing and one in-flight
send. A skipped attempt is not scheduled for later. This explains why
frequent moves can leave loss even at the previously successful 300-ms RTT.
The high-PPS pair is a saturation diagnostic: CPU reaches 100% even with
recovery off. It cannot isolate the replay budget's effect. As a bound,
at 24,000 outer packets/s, 4096 packets cover about 171 ms. Application PPS
and encrypted packet counts should not be treated as interchangeable without observation.
No per-attempt replay trace was added in this stage.

Four new deterministic Go tests check the exact 500-ms edge, eviction by
another peer, the newest suffix under the byte budget, and the pinned
client replay window. With 1400-byte cached packets, the 2-MiB send budget
selects 1497 of 2000 packets. The pinned replay filter accepts an unseen
counter 8128 behind its greatest counter, rejects a duplicate, and rejects
an unseen counter 8129 behind. Key/peer isolation remains covered by the
existing tests. These are unit-level boundaries, not new WAN tests of
physical GUI clients or live key rotation.

## Startup and harness findings

RTT 1400 ms with 140-ms jitter failed admission before noise or useful load
in two attempts. Continuous warmup did not establish the control channel.
The helper uses a one-second TCP connect timeout and a one-second server
TLS-handshake timeout. A separate diagnostic got 0/3 raw TCP connections
with a one-second deadline and 3/3 with four seconds, taking 1.32 to 1.60 s.
Those TCP successes do not establish full mTLS operation at this RTT. Helper
timeouts and authentication checks were left unchanged.

Another pre-load attempt failed because B's helper could not bind its TCP
port (`EADDRINUSE`). The old readiness check accepted a stale Unix socket.
The helper now sets `SO_REUSEADDR` before binding; the harness also requires
a live service PID owning the TCP listener. It does not use `SO_REUSEPORT`.
Five connected mutual-TLS stop/restarts passed. An isolated Linux active-close
control could not rebind without reuse and could rebind with it. The exact
old socket state at the original failure was not captured. The helper
version hash is recorded per trial; this fix changes listener setup only.

One gate workload is excluded: a new nftables fixture had a missing delimiter,
so the atomic NAT/gate transaction was rejected and the requested move never
occurred. The corrected table passed syntax checking, installation and removal
before retry. A first retry then refused to reuse its existing capture
directory before load; the counted retry uses another iteration ID. Old
captures and logs remain private and unchanged. The initial serial warmup
was replaced by bounded continuous 10-pps warmup for both profiles, stopped
before captures, counters and load. Proof freshness/deadlines were preserved.

The first 24,000/s disabled attempt is also excluded: B's full UDP capture
dropped 408,607 frames with the 4-MiB buffer and 32-MiB process ceiling.
The larger-buffer retries retain complete packets and still require zero
capture drops. No VPN loss count is inferred from the incomplete capture.

## Checks and disposition

The Go device/replay suites passed 25 top-level tests; 2 upstream
tests remain skipped. Seven Python agent tests pass on Windows and both
Linux server guests after the listener fix. The patcher copies the new
boundary tests into a clean pinned source tree and rejects a second
application without mutation. Builds did not overlap traffic measurements.

Before shutdown, the stock B command, binary and environment, ordinary DNAT,
original client NAT and profiles were restored. Both native probes passed.
Owned delay/IFB, gate, rules, helpers, warmups and captures were removed or
stopped. All four VMs, the seed server and switch are stopped; eleven
loopback ports are free. Backing disks, prior reports/data and personal JSON
match their original hashes. GitHub and Windows networking were not changed.

Keep return recovery experimental and disabled by default. A useful next
candidate is a bounded deferred attempt for a still-current authenticated
endpoint after the cooldown, followed by a measured choice of history size.
Memory, replay-window and traffic limits still apply. Registered peers can
trigger bounded amplification without proving return reachability, and
repeated ciphertext remains linkable. Physical GUI clients, DPI, distributed
noise and state exhaustion were not tested.
