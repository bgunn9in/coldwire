# Late replies: submission cost and the roaming delay budget

English | [Русский](validation-v26.ru.md)

Measurements in UTC: 2026-11-14. The seven late v25 replies
also arrived late in client packet captures: 1004.302 to
1153.665 ms. Application receive lag after capture was only
0.043 to 0.391 ms. The one-second probe deadline remains unchanged.

The new batch workspace reduced the last submission in the first three-move
comparison from 34.548 to 19.821 ms. It did not remove all late replies.
Across seven candidate trials, unique useful UDP delivery was
2,534,161 sent, 0 missing. Ordinary probes returned
1398/1400 on time and 2 late; frequent probes returned
681/700 on time and 19 late, with
700/700 replies in captures. See [data](results-v26.json)
and [v25](validation-v25.md).

## What was changed

Selected ciphertext copies have no spare capacity. The pinned standard bind
requires that space for UDP GSO coalescing, so old recovery submissions could
not use the same grouping as ordinary outbound traffic. Each current batch now
uses a reusable contiguous workspace. It preserves individual datagram contents,
order, retained snapshots and all key/endpoint checks. The workspace is at most
one batch, bounded by the 2-MiB attempt budget; the usual 128 x 204-byte batch
uses about 25.5 KiB. It is temporary, with no new pool, worker or timer.

The standard bind reports `ErrUDPGSODisabled` even when its individual-send
retry succeeds. Recovery now inspects `RetryErr` and continues the remaining
batches after a successful retry. A real retry error stops the attempt.
Tests exercise success, both error paths, workspace reuse/ownership and an
endpoint change between batches, alongside existing real-ciphertext recovery tests.

Both control and candidate record a rare authenticated-endpoint event and
completed submission timing. Counts describe fully accepted submissions,
not delivery receipts. Journal event timing is approximate; elapsed send
duration uses a monotonic clock inside the function. The baseline is v25
logic plus these same low-rate diagnostic logs. The public standard bind
and client binaries are unchanged.

The ring remains 8192 packets / 8 MiB / 500 ms. Shared retained state remains
16 peers / 8192 packets / 2 MiB with its original 1100-ms expiry. Attempts
remain 8192 packets / 2 MiB, at least 250 ms apart per peer and globally,
with one send in progress. No deadline, source policy or authentication
condition was relaxed. Normal installers still do not deploy this prototype.

## Comparison and timing limits

Four fresh Debian 13 guests ran kernel 6.12.116 under QEMU 11.1.3/WHPX,
each with one vCPU and 1024 MiB, without CPU quotas or a threshold. Traffic
is the previous 25,000 noise datagrams/s for 70 seconds, 64 ports at one
source, plus reverse useful UDP at 6000 datagrams/s with 128-byte payloads for 60 seconds
requested. The same separate iperf3 3.18 startup-reorder benchmark is used.
Complete inner captures count unique datagrams including GSO/GRO; application
loss estimates remain separate. Captured delivery does not prove application consumption.

Netem applies half the requested RTT in each A-B direction, including mTLS,
with jitter 30 ms at RTT 300 or 15 ms at RTT 150, a 16,384-packet queue and no configured
random loss. Twenty physical pings check each setup. Each NAT move starts
100 or 250 ms after the previous conntrack deletion finishes. The actual
first-to-last completion span is in the table: command execution adds time
beyond the nominal gap. Profiles, keys, native ports and the corrected gateway
INPUT model from v24/v25 are unchanged. One profile moves, the other stays put.

Each profile sends 100 ordinary probes at 500-ms intervals; profile 1 sends
another 100 at 50-ms intervals near movement. Client request/reply captures
provide same-clock RTT. Cross-VM wall-clock decompositions are approximate.
The trace separates original echo generation, NAT completions, fresh endpoint,
selection and send completion. Subtracting measured waiting and the entire
send duration is illustrative budget arithmetic, not a causal counterfactual.

| Trial | RTT / jitter ms | Moves / gap ms | Actual NAT span ms | UDP missing | Ordinary timely | Frequent timely / late | Max send ms | Peak CPU % |
|---|---|---|---|---|---|---|---|---|
| baselinetripleretry | 300 / 30 | 3 / 250 | 552.09 | 0 | 199 | 91 / 9 | 34.548 | 88.46 |
| packedtriple | 300 / 30 | 3 / 250 | 551.30 | 0 | 199 | 91 / 9 | 19.821 | 55.00 |
| packedtriplerepeat | 300 / 30 | 3 / 250 | 552.16 | 0 | 199 | 92 / 8 | 23.221 | 67.86 |
| baselineport | 300 / 30 | 2 / 250 | 275.76 | 0 | 200 | 100 / 0 | 23.141 | 72.41 |
| packedport | 300 / 30 | 2 / 250 | 276.06 | 0 | 200 | 100 / 0 | 14.874 | 63.16 |
| baselinebothrepeat | 300 / 30 | 2 / 250 | 275.78 | 0 | 200 | 99 / 1 | 24.165 | 65.22 |
| packedboth | 300 / 30 | 2 / 250 | 275.89 | 0 | 200 | 100 / 0 | 29.626 | 63.64 |
| packedtriple100 | 300 / 30 | 3 / 100 | 255.97 | 0 | 200 | 100 / 0 | 13.618 | 57.89 |
| packedip | 300 / 30 | 2 / 250 | 276.50 | 0 | 200 | 98 / 2 | 14.662 | 68.00 |
| nogsotriple | 300 / 30 | 3 / 250 | 552.14 | 0 | 199 | 94 / 6 | 54.841 | 71.43 |
| baselinetriple150 | 150 / 15 | 3 / 250 | 572.86 | 0 | 200 | 100 / 0 | 42.660 | 66.67 |
| packedtriple150 | 150 / 15 | 3 / 250 | 572.92 | 0 | 200 | 100 / 0 | 19.407 | 55.00 |
| baselineboth | 300 / 30 | 2 / 250 | 275.85 | 0 | 200 | 100 / 0 | 20.043 | 73.08 |

The first nine rows are primary trials. The final four are diagnostics:
`nogsotriple` privately disables all exit IPv4 TX GSO, including ordinary
traffic; it is not an isolated replay-only control. Its bind change is not
published. The 150-ms pair tests a smaller WAN delay/jitter budget. The last
row is a valid control before the lab-network incident below. GSO changes SKB
grouping and how seeded netem jitter is applied, so equal configured shaping
does not give identical per-datagram delay draws or a statistical guarantee.

Successive mappings can disappear while earlier replies and recovery copies
are still travelling. A later address must first send valid current-key
transport through the delayed path before B can safely use it. The reply then
travels back. Faster submission cannot eliminate these intervals or make an
unknown endpoint trusted. The observed three-move cases still exceed the
one-second budget. Recovery preserves delivery; it is not a real-time deadline promise.

All 13 completed noise and useful source rates qualified within 1%. They offered
22,750,000 noise datagrams. NFQUEUE/netlink, client/control guard,
netem qdisc, capture and switch-drop deltas were zero in completed windows.
No noise lease or duplicate plaintext was observed. Candidate whole-VM CPU peaks:
entry 45.83%, exit 68.00%, client 54.17%, attacker 15.38%.
Exit AWG peak RSS was 73.06 MiB with the same 96-MiB
Go soft memory limit. This is not a maximum-throughput or higher-PPS test.

## One excluded infrastructure failure

An initial three-move control lost the client VM's laboratory Ethernet TCP
port. Its independent management NIC and guest stayed alive, but physical
client-to-entry/exit pings failed. The switch had three ports, a 4-MiB backlog
and 71,620 drops. The resident collector subsequently exceeded 400 samples/100 s.
The first trigger of the port loss was not captured. This acquisition has
no valid latency or delivery result and is retained separately in the data.

Captures, journals and state were saved privately. Only the client VM was
restarted; its alias, identical gateway guard and both native profiles were
restored and probed. Completed trials require four connected lab ports and
zero switch-drop delta. Historical cumulative switch counters include the
failed acquisition and must not be read as losses in subsequent trials.

## Checks and disposition

The candidate passed 34 Go tests with two upstream skips, all Coldwire device
race tests, and seven Python helper tests on Windows and both server guests.
The clean pinned patch matches all hook files and rejects reapplication
without mutation. Cached offline builds ran in a one-core/1-GiB guest before
traffic; source snapshots and hashes are recorded per variant.

Stock exit binary/unit/environment, original client NAT/profiles and ordinary
DNAT were restored and both native probes passed before shutdown. All four
VMs and owned seed/switch helpers are stopped, eleven loopback ports are free,
and backing disks, earlier evidence and personal JSON match initial hashes.
Production servers, the user's VPN and Windows networking were untouched;
GitHub was not updated during this lab run.

Keep recovery off on active servers. GUI clients, DPI, multiple moving peers,
distributed noise, state exhaustion and higher PPS/large-packet workloads
remain untested. Registered peers can still trigger bounded amplification
without return-reachability proof; repeated ciphertext remains linkable.
