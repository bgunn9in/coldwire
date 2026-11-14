# Keeping recovery history across successive NAT moves

English | [Русский](validation-v25.ru.md)

Measurements in UTC: 2026-11-14. Across seven final
trials, complete receiver captures account for all 2,535,070
useful UDP datagrams sent.
The ordinary probes returned 1400/1400 on time.
Frequent probes returned 693/700 on time,
7 late, with 700/700 replies in captures.
These are observations of the tested cases, with an unchanged one-second
deadline. They do not establish lossless roaming in general.

The three paired two-move cases changed UDP loss from 1048 to
0 for IP-only moves, 564 to 0
for port-only moves, and 1071 to 0 for both.
See the [data](results-v25.json) and [previous study](validation-v24.md).
The option remains experimental and off by default. Production servers,
the user's VPN and Windows networking were untouched. During the lab run,
no GitHub publication was performed.

## What the controls showed

V24 can lose an earlier recovery window when another authenticated move
creates a newer frozen snapshot. Offline missing-packet ages also overlap
the client's finite replay-window boundary. Old captures do not expose
the client's internal reject reason, so age alone cannot prove rejection.

`fast` shortens the per-peer pause to 500 ms with the old snapshot logic.
It still loses 785 and 831 unique UDP datagrams. `refresh` retains the first
selection, adds newer replies on another move, and raises the packet ceiling
within the same byte budget. Its two trials lose no UDP, but four and five
frequent replies miss the deadline. `early` reduces the pause to 250 ms.
Two moves and three 100-ms moves pass, but three 250-ms moves lose 2466 UDP
datagrams. Its attempt log shows a recovery towards the second path followed
by a fresh ring selection for the third, after the earlier snapshot was freed.

The final change keeps that snapshot after each attempt until its original
deadline. Another fresh authenticated move can rearm it and add newer eligible
replies. Stable traffic cannot rearm it. The controls below remain part of
the record; failed candidates are not counted as final-build successes.

| Trial | Moves / gap ms | UDP missing / sent | Ordinary timely | Frequent timely / late / captured | Peak CPU % |
|---|---|---|---|---|---|
| fastboth | 2 / 250 | 785 / 362655 | 200 | 94 / 2 / 96 | 73.68 |
| fasttriple | 3 / 100 | 831 / 362186 | 200 | 94 / 4 / 98 | 66.67 |
| refreshboth | 2 / 250 | 0 / 362106 | 200 | 96 / 4 / 100 | 81.48 |
| refreshtriple | 3 / 100 | 0 / 362099 | 200 | 95 / 5 / 100 | 73.68 |
| earlyboth | 2 / 250 | 0 / 362017 | 200 | 100 / 0 / 100 | 76.00 |
| earlytriple | 3 / 100 | 0 / 361798 | 200 | 100 / 0 / 100 | 74.07 |
| earlytriple250 | 3 / 250 | 2466 / 362442 | 199 | 93 / 0 / 93 | 78.26 |

## Bounds and ownership

The ordinary ring remains 8192 packets / 8 MiB / 500-ms eligibility.
All retained state shares 16 peers / 8192 packets / 2 MiB. Each attempt is
also limited to 8192 packets and 2 MiB. The packet ceiling rose from 4096;
the ciphertext byte budgets did not change. Local insertion sequences allow
only newer ring entries to be added. The first selection's ciphertext is
reused without another payload copy; additions are copied once.

Each snapshot expires 1100 ms after its creation. Retargeting, appending and
sending never extend it. The existing 100-ms cleanup tick releases idle
state; no per-peer timer or worker was added. The minimum interval is 250 ms
both per peer and globally for nonempty attempts, with one send in progress.
The global allowance is unchanged, but one peer can now use all of it.

Recovery requires fresh authenticated current-key transport and a valid
source policy. Running/open/roaming state and the current destination are
checked; every batch rechecks key and destination. Buffers contain ciphertext,
public-key hashes and scalar ownership/order/address metadata, without
plaintext, session keys or peer/keypair references. Already submitted packets
cannot be recalled. A confirmed address can disappear before replies arrive.

## Equal-model VM comparison

Four fresh Debian 13 COW guests ran kernel 6.12.116 under QEMU11.1.3/WHPX,
each with one vCPU and 1024 MiB. No CPU quota or threshold applies. Noise is
25,000 datagrams/s for 70 seconds, one source IPv4 and 64 ports in 4096-packet
bursts. The payload has a captured transport prefix and altered ciphertext.
Reverse useful UDP requests 6000 application datagrams/s with 128-byte
payloads for 60 seconds. This is the same separate iperf3 3.18 startup-reorder
benchmark used in v22-v24; actual sender durations and counts are retained.

RTT is 300 ms, with 150-ms netem delay and 30-ms normal jitter per A-B
direction, including mTLS. Queues hold 16,384 packets without configured
random loss. Twenty physical pings check each setup. Only the disposable
gateway changes NAT. Client profiles, keys, listen ports and native binaries
remain unchanged. One profile moves; the other supplies stationary probes.

All variants use the corrected gateway INPUT model from v24. Only unmatched
local reverse UDP is dropped before conntrack confirmation. Reverse-DNAT
traffic continues through FORWARD. The isolated negative control was v24;
it was not repeated here. This does not establish every real router's behavior.

Complete inner captures count unique UDP delivery including GSO/GRO and
the short control tail. Iperf loss is separate. Captured delivery does not
prove application consumption. Each profile sends 100 ordinary probes at
500-ms intervals, plus 100 frequent probes at 50-ms intervals near movement.
The deadline remains one second; late replies and captured replies stay separate.

| Trial | Moves / gap ms | UDP missing / sent | Ordinary timely | Frequent timely / late / captured | Peak CPU % |
|---|---|---|---|---|---|
| baselineboth | 2 / 250 | 1071 / 362373 | 199 | 89 / 9 / 98 | 91.67 |
| baselineip | 2 / 250 | 1048 / 362550 | 200 | 90 / 6 / 96 | 72.41 |
| baselineport | 2 / 250 | 564 / 362006 | 199 | 89 / 8 / 97 | 63.33 |
| finalboth | 2 / 250 | 0 / 362200 | 200 | 100 / 0 / 100 | 80.77 |
| finalip | 2 / 250 | 0 / 362508 | 200 | 100 / 0 / 100 | 81.48 |
| finalport | 2 / 250 | 0 / 361950 | 200 | 99 / 1 / 100 | 81.48 |
| finaltriple100 | 3 / 100 | 0 / 361980 | 200 | 100 / 0 / 100 | 76.92 |
| finaltriple250 | 3 / 250 | 0 / 362081 | 200 | 95 / 5 / 100 | 80.95 |
| finalbothrepeat | 2 / 250 | 0 / 362437 | 200 | 99 / 1 / 100 | 80.95 |
| finalstable1200 | 2 / 1200 | 0 / 361914 | 200 | 100 / 0 / 100 | 79.31 |

All 17 offered noise and useful source rates qualified within 1%.
Noise totalled 29,750,000 datagrams. NFQUEUE/netlink, client/control
guard, netem qdisc, switch and capture drops were zero. Noise obtained no
lease; no duplicate plaintext was observed. Expected stale-NAT INPUT drops
are recorded separately. Journal entries describe selected attempts, not
delivery receipts. The last final-build attempt matches the final authenticated
translated target in each case.

Final-build whole-VM CPU peaks by role were
entry 50.00%, exit 81.48%, client 65.38%, attacker 18.52%.
Exit AWG peak RSS was 79.16 MiB with the same
96-MiB Go soft memory limit. This traffic profile does not measure maximum
VPN throughput or a higher-PPS client.

## Verification and remaining work

The final source passed 33 Go tests, with two upstream skips, and all
Coldwire device tests passed the race detector in a one-core/1-GiB VM.
Tests cover shared budgets, an unarmed held snapshot, insertion watermark,
overlap/order, unchanged deadline, current-key/address guards, concurrent
cleanup and two deliberately dropped encrypted packets recovered across
separate attempts without duplicate plaintext. Seven Python helper tests
pass on Windows and both server guests. The pinned patch matches its clean
source and rejects reapplication without mutation. Builds use cached tools
and modules offline; no compilation overlaps traffic. Each variant has an
immutable source snapshot and binary hash in the data.

Before shutdown, stock exit binary/unit/environment, ordinary DNAT and
original client NAT/profiles were restored, and both native probes passed.
All four VMs, seed and switch are stopped; eleven loopback ports are free.
Backing disks, earlier evidence and personal JSON match their initial hashes.

Keep recovery off on active servers. Higher PPS or larger packets can outrun
the replay window or byte budget. A sequence of moves can outlast 1100 ms;
one peer can occupy the shared recovery budget. Concurrent moving peers,
physical Windows/macOS/Android/iOS GUI clients, DPI, distributed noise and
state exhaustion were not tested. Authenticated peers can still cause bounded
amplification without proving return reachability. Repeated ciphertext remains
visible and linkable.
