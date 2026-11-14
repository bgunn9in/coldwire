# A bounded retry after a fast NAT move

English | [Русский](validation-v24.ru.md)

Measurements in UTC: 2026-11-14. The new pending snapshot
reduced network loss in all three paired 250-ms movement cases. IP-only
loss changed from 3768 to 1077 UDP datagrams, port-only
from 3491 to 982, and IP plus port from
3358 to 663. The extra IP-plus-port repetition lost
911. These are bounded observations, with residual
loss and late replies. See [data](results-v24.json) and [v23](validation-v23.md).

The option remains experimental and disabled by default. Native client
binaries, profiles, keys and ports are unchanged. No production server,
user VPN or Windows networking was modified. GitHub was not updated.

## Pending snapshot and limits

The ordinary ring still holds at most 8192 packets and 8 MiB, with 500-ms
eligibility. If a changed authenticated endpoint hits a cooldown or busy
sender, the patch can copy one eligible snapshot for that peer. All pending
state shares a limit of 16 peers, 4096 packets and 2 MiB. It retains encrypted
packets, a public-key hash, scalar key epoch and an address string. It keeps
no plaintext, session keys, peer pointers or keypair pointers.

Another fresh move retargets the existing snapshot without another payload
copy or a longer deadline. After cooldown, the next fresh transport proof
can consume that snapshot once, provided the current key, source-policy check
and endpoint still agree. A stopped peer, closed device or disabled roaming
prevents a new retry. Each send batch rechecks key and endpoint. Packets
already submitted to the network cannot be recalled.

The per-peer interval remains one second, including empty immediate lookups;
nonempty attempts are at least 250 ms apart globally, with one in-flight send.
Pending eligibility ends after 1100 ms. The existing 100-ms cleanup tick also
releases idle pending state. No new per-peer timer or worker is created.
Without another qualifying client packet before expiry, no retry occurs.
Selected pending ciphertext can be older than the ordinary 500-ms ring;
the client's existing replay-window checks remain in force.

## Setup and primary trials

Four fresh Debian 13 COW guests ran kernel 6.12.116 under QEMU 11.1.3/WHPX,
each with one vCPU and 1024 MiB. A is the entry, B the exit, C the client
gateway and D the noise source. CPU has no quota or acceptance threshold.
One native profile moves; the second sends stationary control probes.

Each trial offers 25,000 noise datagrams/s for 70 seconds from one IPv4
address and 64 ports, in 4096-packet bursts. Noise uses a captured transport
prefix with altered ciphertext. Reverse useful UDP requests 6000 application
datagrams/s, 128-byte payloads, for 60 seconds. It uses the same separate
iperf3 3.18 startup-reorder benchmark as v22/v23. Sender durations/counts are
retained because reverse control exchanges can extend sending.

The first gateway NAT change occurs 25 seconds after workload launch. Later
moves start 100, 250 or 1200 ms after the preceding conntrack deletion ends.
Netem adds half the requested RTT in each A-B direction, including mTLS,
normal jitter of 10% of RTT per direction, and 16,384-packet queues without
random loss. Twenty physical pings check each RTT. Management and noise
delivery have no added delay. Legacy and new builds use the same corrected
gateway model described below.

Complete inner UDP captures establish unique tunnel delivery, including
GSO/GRO and the short control tail. Iperf's separate loss estimate does not
define these counts or prove application consumption. Each profile sends
100 ordinary probes at 500-ms intervals; profile 1 sends another 100 at
50-ms intervals near movement. The deadline stays one second. "Captured"
includes late replies and replies arriving after the probe stopped reading.

| Build | Move | RTT / jitter ms | Moves / gap ms | UDP missing / sent | Frequent: timely / late / captured | Deferred attempts | Peak CPU % |
|---|---|---|---|---|---|---|---|
| legacy | IP | 300 / 30 | 2 / 250 | 3768 / 362000 | 89 / 0 / 89 | 0 | 72.73 |
| deferred | IP | 300 / 30 | 2 / 250 | 1077 / 361960 | 87 / 8 / 95 | 1 | 83.33 |
| legacy | Port | 300 / 30 | 2 / 250 | 3491 / 361924 | 88 / 0 / 88 | 0 | 79.31 |
| deferred | Port | 300 / 30 | 2 / 250 | 982 / 362007 | 89 / 10 / 99 | 1 | 68.42 |
| legacy | IP + port | 300 / 30 | 2 / 250 | 3358 / 362821 | 90 / 0 / 90 | 0 | 77.78 |
| deferred | IP + port | 300 / 30 | 2 / 250 | 663 / 362102 | 88 / 9 / 97 | 1 | 81.48 |
| deferred repeat | IP + port | 300 / 30 | 2 / 250 | 911 / 362277 | 88 / 8 / 96 | 1 | 79.31 |
| deferred | IP + port | 300 / 30 | 3 / 100 | 918 / 362119 | 89 / 7 / 96 | 1 | 65.00 |
| deferred | IP + port | 300 / 30 | 2 / 1200 | 0 / 362173 | 100 / 0 / 100 | 0 | 69.57 |
| deferred | IP + port | 150 / 15 | 2 / 250 | 0 / 361064 | 97 / 3 / 100 | 1 | 70.83 |

The journal records 6 deferred attempts, each towards the
last authenticated translated target rather than the intermediate port.
Their intervals from the preceding attempt were 1008.85 to
1107.94 ms. A log entry reports selection for an attempt, not
delivery. The table comes from the independent inner captures. Single cases
and one extra repetition do not establish a confidence interval or a
lossless-roaming guarantee.

All ten primary trials qualified noise and useful source rates within 1%.
They offered 17,500,000 noise datagrams. Client/control guard,
NFQUEUE/netlink, netem qdisc, switch and capture drops were zero. Noise
obtained no lease; no plaintext duplicates were observed. Expected drops
of old, unmapped traffic at the client gateway are recorded separately.
Peak whole-VM CPU by role was entry 52.00%, exit 83.33%, client 53.85%, attacker 18.52%.
B's AWG RSS high-water mark was 73.23 MiB with the
unchanged 96-MiB Go soft memory limit. No guest logged an OOM or replay-send error.

## Correcting the gateway model

Four preliminary trials used the permissive Linux gateway from earlier
studies. Returning to the same IP and port produced a long independent
failure: an old-path UDP packet reached local INPUT and created an
unmanaged reverse conntrack tuple. That tuple prevented reuse of the fixed
source mapping. The legacy IP-only run lost 373,837 UDP datagrams and its
sender continued for 86.59 seconds. A preliminary new-build attempt exceeded
the resident collector's 400-sample/100-second limit, so it has no valid
delivery result. The data keeps these preliminary results separately.

An isolated diagnostic outside the VPN reproduced the failure on separate
UDP ports. Initial and intermediate echoes worked, but the final return
timed out. Dropping only unmatched local INPUT before conntrack confirmation
prevented the unwanted tuple and the return echo worked. Valid reverse-DNAT
traffic traverses FORWARD and continued to pass both native probes.

All ten primary trials use that INPUT guard in C, identically for both
builds. It models a gateway that drops unsolicited traffic to closed NAT
mappings. It changes no VPN client, entry filter, production router or host
firewall. The guard is removed at cleanup. These results do not guarantee
the behavior of every real router configuration.

## Checks and disposition

The final source passed 31 Go device/replay tests; two upstream tests remain
skipped. All Coldwire device tests also passed the race detector, including
concurrent queue/take/prune. Six new tests cover frozen ownership, retargeting,
expiry, global budgets/spacing, active-state/key/address guards and recovery
of deliberately dropped real ciphertext without duplicate plaintext.
Seven Python helper tests pass on Windows and both Linux server guests.
The patcher reproduces all hook sources on a clean pinned tree and rejects
a second application without mutation.

The exit initially had no C compiler for `-race`; a stalled package download
was stopped before measurements. Cached Go tools, modules and source were
copied locally to the entry guest, where the compiler already existed.
Final normal and race tests ran there within one vCPU/1024 MiB. No build
overlapped traffic measurements. The production source stayed unchanged
during the matrix; the final test refinement isolates each runtime guard.
Binary and source hashes are in the data.

Before shutdown, stock B binary/unit/environment, ordinary DNAT and original
client NAT/profiles were restored, and both native probes passed. The lab
NAT guard, diagnostics, impairments, helpers and captures were removed or
stopped. All four guests, seed server and switch are off; eleven loopback
ports are free. Backing disks, previous reports/data and personal JSON match
their initial hashes. No background research or chat monitoring remains.

Keep the option off on active servers. A frozen snapshot misses replies
generated during later moves; the age, memory and replay-window limits still
apply. Recovery can improve delivery while missing the one-second probe
deadline. Multiple peers moving together, physical GUI clients, DPI,
distributed noise and state exhaustion were not measured. Registered peers
can still trigger bounded amplification without return reachability proof;
repeated ciphertext remains linkable.
