# v32: New-flow confirmation and admission loss

English | [Русский](validation-v32.ru.md)

The prototype now preserves the conntrack generation checked for an early
candidate and wakes its scheduler when an authenticated hint first raises
that candidate's priority. Exit-side local proof notifications are eligible
every 10 ms instead of 50 ms. Ciphertext recovery keeps its 250-ms spacing.
Normal installers still disable the prototype.

The historical loss of 659 UDP packets is not proved fixed. Ordinary trials
in this study delivered every unique useful UDP packet. Deleting one pending
conntrack generation deliberately reproduced a similar admission failure:
its held packets expired after the proof could no longer match a current
mapping. Accepting that stale proof would weaken the authorization check.

Production servers, the user's VPN and host networking were untouched.
Clients kept their binaries, profiles, keys and listening ports.

## Changes and regression checks

An early candidate already contains an original tuple and conntrack ID.
A validated them with an exact GET, then looked up the translated reply port
again through the hint handler. Replacement of the mapping between those
lookups could switch the cached candidate to another generation. A now stores
the first checked result directly. It still rechecks the mapping when the
nonce proof arrives. A regression substitutes another generation for that
second lookup and verifies that it cannot replace or authorize the candidate.

An authenticated hint for a recently cached candidate used to change its
priority without waking the scheduler. It could wait for the next 100-ms
cycle. The first priority upgrade now wakes it; repeated hints at the same
priority do not. Neither candidates nor hints grant a lease. Another
regression checks the wakeup and the absence of authorization.

B's local event throttle contributes to the wait for an event generated
after the nonce request. Its eligibility interval is now 10 ms. This changes
root-only Unix datagrams, not the client protocol or ciphertext replay rate.
There is no added timer or worker. An eligible notification still needs a
fresh authenticated packet; scheduling and sparse traffic can delay it.
The helper's separate per-port hint interval and global hint budget are
unchanged. Proof freshness, current key/counter ordering, inner-source policy,
pending-request bounds, conntrack generation and expiry remain mandatory.

Both agent regressions fail on the old source. In a one-core, 1024-MiB guest,
16 agent tests and five conntrack tests passed. The 10-ms Go boundary test
fails with the old interval. The rebuilt receiver passed 37 top-level Go
tests with two upstream skips, plus all Coldwire race tests. The guard that
coalesces moves at 100 and 200 ms into a retry at 250 ms still passes.

## Measurement method

Four local Debian 13 guests ran kernel 6.12.116 under QEMU/WHPX. Each had one
vCPU and 1024 MiB RAM, without a CPU quota or acceptance threshold. Trials
offered 25,000 noise packets/s from 16 IPs and 6000 useful UDP packets/s.
The WAN model requested 300-ms RTT with 30-ms normal jitter per direction.
The gateway changed the moving client's apparent IP and NAT port three times,
with a requested 250-ms gap. The native clients themselves did not change.

The small-packet upload used 128-byte UDP payloads and 8192 noise flows.
A stationary client's SNAT mapping deliberately occupied the moving client's
middle source port, forcing a translated-port collision. Download used
1200-byte payloads and 64 noise flows. These are separate workload shapes.
Independent source/switch counters qualified the noise rate; complete inner
UDP sequence sets measured delivery after capture drain. Iperf's reported
loss includes packets recovered late or reordered and is kept separately.

Private diagnostic builds kept at most 16,384 timeline records in RAM and
64 selected lab-client flow counters. They recorded no payload and performed
no per-packet file writes. Selection by lab address affected telemetry only,
never admission. No diagnostic ring overflowed. One plain control and its
instrumented repeat both delivered all useful UDP, with similar mean entry
CPU (31.67% and 32.13%). This is a small calibration, not proof of zero
observer cost. No full outer packet capture was used in performance trials.

Nonce joins connect A's query to B's post-query event and A's confirmation.
Durations use one VM's monotonic clock: A measures query to confirmation;
B measures query cutoff to fresh authenticated event. Cross-VM clock
subtraction is not used to claim precise link latency. Steady-flow summaries
exclude the traffic drain; idle old tuples and the low-PPS second client
would otherwise distort the notification comparison.

## Results

The selected comparisons below have zero switch, capture-ring and WAN-queue
drops. No noise tuple received a lease or used the trusted path. All native
client integrity checks passed. Across 13 trials without forced deletion,
all 4,684,171 unique useful UDP packets arrived; 26 of 1300 ICMP replies
arrived after one second, and none was missing. Trial results, counter deltas,
CPU summaries and sample-file hashes, memory, source/binary hashes and timing
joins are in [the data](results-v32.json). Raw CPU samples remain local.

| Workload | Agent / local event interval | Useful UDP missing | ICMP >1 s / missing | Max ICMP RTT, ms |
|---|---|---:|---:|---:|
| upload, collision, run 1 | old / 50 ms | 0 | 0 / 0 | 919.566 |
| upload, collision, run 2 | old / 50 ms | 0 | 1 / 0 | 1097.183 |
| upload, collision, run 1 | fixed / 50 ms | 0 | 0 / 0 | 955.520 |
| upload, collision, run 2 | fixed / 50 ms | 0 | 0 / 0 | 974.593 |
| upload, collision, run 1 | fixed / 10 ms | 0 | 0 / 0 | 938.555 |
| upload, collision, run 2 | fixed / 10 ms | 0 | 0 / 0 | 838.457 |
| download, 1200 B | old / 50 ms | 0 | 11 / 0 | 1418.476 |
| download, 1200 B | fixed / 10 ms | 0 | 12 / 0 | 1524.666 |
| upload, collision, conntrack 16384 | fixed / 10 ms | 0 | 0 / 0 | 823.883 |

For the fixed-agent upload pairs, the median fresh-event wait across the
first queries for six changed mappings fell from 29.436 to 8.021 ms.
A's median query-to-confirmation time fell from 358.571 to 323.799 ms.
There are only two runs per interval, with independent jitter realizations.
These observations support keeping the shorter local throttle; they do not
establish a percentile bound or a reliable improvement in the download tail.
The latter still contains replies over 1.5 seconds.

In those upload pairs, mean entry CPU was 30.60% and 31.80% at 50 ms,
versus 31.51% and 30.97% at 10 ms. Mean exit CPU was 31.53% and 32.58%,
versus 33.59% and 32.69%. The 10-ms trials retained at least 688,228 KiB
available on A and 525,964 KiB on B. The download pair used mean exit CPU
57.54% and 51.57%; one pair cannot establish a CPU saving. No new CPU limit
was applied. Local notification volume rises with the shorter throttle.

The 16384-entry headroom trial peaked at 9734 conntrack entries, recorded
zero `early_drop`, `drop` and `insert_failed` deltas, and delivered all useful
packets. Mean entry CPU was 30.38%, with at least 688,072 KiB available.
At capacity 8192, two fixed/10-ms trials recorded 2505 and 2677
`early_drop` events, and 2073 and 2420 `drop` events. Client delivery still
had no loss, so these aggregate counters cannot identify a client victim.
Earlier traces did not sample these counters; absence is recorded as unknown.
The larger capacity was a lab-only setting, restored afterwards. No installer
or deployment sysctl was changed. A finite conntrack table can fill again
under another workload.

An initial acquisition dropped 57,731 switch frames and missed 89,127 noise
frames at entry. Its source offered the requested rate, but delivery did not
qualify. It is retained separately and excluded from performance conclusions.
The exact cause of that isolated infrastructure failure was not established.

## What happened to the 659 packets

The original v31 capture proves 659 missing unique UDP packets and one
missing ICMP reply, with 660 early entry drops. The missing UDP packets were
sent 23.708496 to 24.217493 seconds after the first source packet, during
three gateway changes. The middle mapping never obtained a lease. Its
translated source port differed from its original port. The old evidence
lacks per-client expiry/rejection and nonce timing, so it cannot establish
which conntrack operation caused that failure. NAT-port collision alone and
an explicit rerun with v31's rejected replay binary did not reproduce it.

For a controlled failure, the lab deleted exactly the middle client's
original-tuple conntrack entry while its proof was pending. The deletion
was guarded by private lab addresses and the entry hostname. Actual operation
times were recorded; SSH/CLI scheduling means they differ from the requested
dispatch time. The next fresh proof arrived after that generation vanished.
A correctly rejected it. In the old-agent case, 665 packets held for that
generation all expired; 663 useful UDP packets and two probes were missing.
With the fixed agent and 50-ms notifications, 656 held packets expired,
654 useful UDP packets and one probe were missing. Other packet types also
contribute to the holding and entry-drop counters.

The fixed/10-ms negative control also rejects the vanished generation:
all 718 held packets expired, with 715 useful UDP packets and two probes
missing. Other client generations were released normally. Faster local
notifications cannot make an absent conntrack mapping valid.

This establishes a failure mechanism, not the exact historical cause.
Under kernel table pressure it is plausible: upstream Linux 6.12's
[early-drop path](https://github.com/torvalds/linux/blob/v6.12/net/netfilter/nf_conntrack_core.c)
can evict eligible unassured connections; its
[UDP tracker](https://github.com/torvalds/linux/blob/v6.12/net/netfilter/nf_conntrack_proto_udp.c)
does not mark a newly bidirectional flow assured immediately, using a
two-second stream threshold. These are upstream reference sources; the
tested guest ran Debian's 6.12.116 kernel. Pressure counters support the
risk, but do not prove that the old missing flow was a kernel eviction.

## Remaining limits

The generation and wakeup defects are fixed, and the shorter local proof
throttle is retained. The observed ordinary workload delivered every unique
useful UDP packet. It still has late responses, and deliberately removing a
pending mapping still loses its held packets. Extending trust to a deleted
generation would not be a safe repair. The next useful check is a bounded
generation-lifetime protection experiment under natural conntrack pressure,
with controls for attack-driven resource retention.

These trials do not promise a one-second deadline, survival of arbitrary
mapping churn, or loss-free operation under DDoS. No new long soak, GUI-client
compatibility, IPv6, DPI-resistance or production-capacity test was performed.
The two unchanged native clients cover wire compatibility in this lab.

## Cleanup

The stock exit service, ordinary DNAT, original client NAT, observation
helpers and conntrack accounting were restored. The collision rule, noise
aliases, WAN impairment and diagnostic jobs were removed. Conntrack capacity
was restored to 8192. Both unchanged native client probes passed before
shutdown. All four VMs and the owned switch/seed processes are stopped;
eleven loopback ports are free. Backing disks, prior reports, personal JSON
and Git HEAD are unchanged. No GitHub push was made.

