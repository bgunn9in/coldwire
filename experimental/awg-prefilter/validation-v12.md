# The last ping: timeout and packet tracing

English | [Русский](validation-v12.ru.md)

Test date: 13 November 2026. The old probe can report 99/100 while all
100 replies reach the client. Three controls reproduced this by delaying
only the last request by 500 ms: its reply arrived 433–476 ms after the
`ping` process had exited. No selected echo packet was lost in those controls.

The new bounded [ICMP probe](lab-switch/icmp-probe.py) returned 1800/1800
replies in nine final runs at verified 25,000 noise packets/s and about
100 Mbit/s TCP. Peak whole-VM CPU was 65.38%, below the 90% threshold.
AWG, the filter, its guard/queue settings and QEMU were unchanged.

The specific v11 event has no packet capture. These controls support a
timeout explanation but do not prove that old packet's fate. Historical
counts and strict-pass scores remain intact.

## Diagnosis

The saved v11 output identifies the missing sequence as 100. That process
had a previous maximum RTT of 7.333 ms. In installed iputils 20240905, the
terminal wait after replies have arrived is twice the maximum RTT, with
an interval floor: about 20 ms here. The harness had incorrectly treated
`-W 1` as a guaranteed one-second final receive period.
[Installed-version source](https://github.com/iputils/iputils/blob/20240905/ping/ping_common.c).

Twelve ordinary legacy-probe runs did not reproduce the rare symptom.
We then delayed only client 2's request 100 by 500 ms, under the unchanged
noise and TCP workload. In each direction, client and exit captures saw
100 requests and replies while the old application counted 99 replies.
Process-exit observations confirmed the late arrival. This demonstrates
a probe-timeout mechanism in the controls. The earlier v11 queue-2048
overflow is a separate real observation and is not explained away.

Captures followed ICMP identifiers and sequences on both client tunnel
interfaces and the exit tunnel interface. Initial diagnostics also sampled
short outer UDP packets. Capture-drop counters, NIC/UDP/softnet/qdisc
errors and raw job output were retained. All analyzed captures reported
zero kernel capture drops. The selected outer captures do not reconstruct
every offloaded datagram.

## Correction and negative controls

The helper uses a Linux raw ICMP socket in the existing lab namespace.
It sends exactly 100 requests, 20 ms apart, with 56-byte payloads. It
validates source, reply type, identifier, sequence, checksum and a per-run
token. Each reply has an explicit one-second monotonic-clock budget,
including reception after the final send. It sends no replacement probes;
JSON reports missing sequences, duplicates and reply timings.

Packet/validation self-tests passed on Windows and Linux. Live tests used
the actual VM stack. With the same delayed-last control, the new helper
received 600/600 replies across three runs. A separate negative control
deliberately dropped client 2's request 50. The helper reported exactly
sequence 50 missing; client/exit captures showed 99 replies, and the
namespace qdisc recorded the drop. Its parent and child counters describe
the same one packet and must not be added together.

Eight initial acquisitions failed to launch a datagram ICMP socket and
are excluded from packet-loss results; one unfinished acquisition was
stopped. The final helper uses a raw socket. The harness now rejects
empty output or startup stderr, rather than classifying a launch error
as 100% packet loss. The rejection self-check passed.

## Final measurements

All four disposable Debian 13 guests retained 1 vCPU and 1024 MiB RAM.
Noise remained 300,000 UDP packets targeting twelve seconds at 25,000/s,
one 256-byte payload per trial and offered bursts up to 4096. Two native
AWG clients requested 50 Mbit/s each. No CPU quota or lower offered rate
was used.

The [JSON](results-v12.json) includes 37 analyzed trials: twelve legacy
baselines, three old-probe delay controls, thirteen corrected-probe runs
with full tracing and nine final repeats with lighter tracing. The switch
and entry independently counted all 11,100,000 offered noise packets in
these analyzed trials. Startup failures are listed separately.

Two diagnostics failed the measurement conditions and were retained.
One reached 100% CPU while `unattended-upgrades` was active. Package jobs
were then confirmed idle and maintenance timers masked only in disposable
guests. Another full-capture run reached 92% and 24,313 packets/s; it was
not accepted as a 25,000-packet/s budget result.

Final repeats kept inner ICMP captures and all loss counters, removing
outer-NIC filtering work from the observer. Three rotated/reversed
repeats per direction all passed rate, throughput, CPU and echo delivery.

| Direction | Median total Mbit/s | A max CPU % | B max CPU % | C max CPU % | D max CPU % | Passed |
|---|---:|---:|---:|---:|---:|---:|
| Both upload | 100.04 | 64.29 | 40.74 | 40.00 | 24.14 | 3/3 |
| Both download | 99.87 | 59.26 | 32.14 | 65.38 | 28.00 | 3/3 |
| Mixed | 99.98 | 62.96 | 32.14 | 47.83 | 27.59 | 3/3 |

Final sender means were 24,999.77–24,999.84 packets/s; total TCP was
99.87–100.05 Mbit/s. All 1800 replies were counted by the helper and seen
at both tunnel endpoints. There were no NFQUEUE/netlink-user, guard,
shaper or switch drops in these repeats. The nominal 250-ms whole-VM
CPU samples and sliding four-sample tick windows include observer cost;
they do not establish an instantaneous CPU ceiling.

Across all analyzed trials, applications counted 7396/7400 replies and
client captures saw 7399 round trips. The difference is the three old-probe
timeout controls. The one absent round trip was the deliberate request-50
drop. Some initial background IPv4 discard counters increased while all
selected ICMP replies were present; aggregate counters were not attributed
to the echo probes.

## Decision and limits

Use the bounded helper for lab echo measurements and retain packet tracing
for any new application/path discrepancy. The final series found no
unexpected ICMP loss at the tested load. It cannot conclusively classify
the single old event without its capture, or establish performance on real
VPS and physical GUI clients. The filter needs no change for the reproduced
probe timeout.

Rollback restored ordinary DNAT, client NAT, runtime port and the original
client qdisc; the delay/drop fixture was removed. Both clients passed
probes, and profile/filter/personal JSON hashes were unchanged. Captures,
all four VMs and both host helpers were stopped; eleven lab ports were
released. Live servers, the user's VPN, WSL and Windows networking were
untouched. English and Russian prose was reviewed with Humanizer.
