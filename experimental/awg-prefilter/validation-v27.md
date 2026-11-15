# Recovery between local notifications

English | [Русский](validation-v27.ru.md)

Measurements in UTC: 2026-11-15.
An eligible recovery in v26 could wait for the next local proof notification.
The notification limit is 50 ms; recovery has its own 250-ms limit. These checks
now run independently. A fresh authenticated packet can trigger an eligible
recovery while its local notification remains suppressed.

The regression fails against v26 and passes with the correction. This fixes
the extra condition in the code. It does not guarantee a shorter WAN RTT in
every trial: successive NAT changes, authentication and return travel still
leave late replies. See [data](results-v27.json) and [v26](validation-v26.md).

## Code and checks

The proof hook keeps the existing current-key, fresh counter and source-policy
checks. Unix socket initialization still requires root ownership and mode 0600;
IPv4 endpoint validation precedes recovery. The 50-ms condition controls notification output only when
recovery is enabled; the disabled path still returns early. Event contents and
notification rate are unchanged. Recovery still checks the peer state, current
endpoint, key and its own cooldown before sending.

The new subtest makes notification eligibility false while a bounded snapshot
is already due. It requires exactly one recovery, no Unix notification and no
rearming on stationary transport. It failed on the unchanged v26 proof hook
and passed after the fix. The candidate passed all 34 Go tests, with two upstream
skips, all Coldwire device race tests, and seven Python helper tests on Windows
and both server guests. A clean pinned patch reproduces the files; reapplying
it is rejected without mutation. Compilation and checks ran before traffic,
offline with cached tools/modules in a one-core/1-GiB guest.

No client profile, key, binary, native port or wire packet was changed. There
is no new setting, worker or timer. The recovery cache, expiry, 250-ms peer/global
spacing and one-send-at-a-time rule stay as in v26. The ordinary ring remains
8192 packets / 8 MiB / 500 ms; pending snapshots share 16 peers / 8192 packets /
2 MiB with their original 1100-ms expiry. Each attempt remains at most 8192
packets / 2 MiB. Normal installers do not enable this experimental feature.

## Paired WAN trials

Four fresh Debian 13 guests ran kernel 6.12.116 under QEMU 11.1.3/WHPX, each
with one vCPU and 1024 MiB. There was no CPU quota or threshold. The measured
traffic was 25,000 noise datagrams/s for 70 seconds across 64 ports at one source,
plus useful UDP at 6000 datagrams/s with 128-byte payloads for 60 seconds requested.
The same separate iperf3 3.18 benchmark handles startup reordering.

Netem applies half of the 300-ms RTT in each A-B direction, including the
control channel, with 30-ms jitter per direction, a 16,384-packet queue and
no configured random loss. Twenty physical pings check each setup. The gateway
changes IP and NAT port three times, or IP alone twice; each change starts
250 ms after the previous conntrack deletion finishes. Actual spans are in
the data. Both native profiles stay unchanged; one moves and one is stationary.

There are 100 ordinary probes per profile at 500-ms intervals and another
100 probes at 50-ms intervals near movement. Their deadline stays one second.
Complete inner captures count unique useful UDP datagrams with GSO/GRO and
verify late ICMP RTT on the client's own clock. Application loss estimates are
separate; capture receipt does not prove application consumption.

The first two pairs repeat the three-move download condition with AB then BA
order and matched seeds within each pair. The IP-only pair uses AB order.
The upload pair uses BA order and checks the extra receive-path work at 6000
packets/s. Both upload variants use identical outer captures, so their cost
must not be compared directly with the leaner download capture setup.

| Trial | Direction | UDP sent / missing | Ordinary timely / 200 | Frequent timely / late | Last endpoint wait ms | Exit mean CPU % | Peak VM CPU % |
|---|---|---|---|---|---|---|---|
| baselineone | download | 362445 / 0 | 199 | 93 / 7 | 58.504 | 52.36 | 74.19 |
| candidateone | download | 361963 / 0 | 199 | 91 / 9 | 102.157 | 32.84 | 69.23 |
| candidatetwo | download | 362128 / 0 | 199 | 92 / 8 | 75.437 | 58.86 | 74.19 |
| baselinetwo | download | 362491 / 0 | 199 | 92 / 8 | 124.684 | 53.40 | 71.43 |
| baselineip | download | 362084 / 0 | 200 | 98 / 2 | 0.000 | 45.79 | 72.00 |
| candidateip | download | 362079 / 0 | 200 | 100 / 0 | 0.000 | 33.23 | 60.00 |
| candidateup | upload | 360006 / 303 | 200 | 99 / 0 | 0.000 | 22.74 | 81.48 |
| baselineup | upload | 360001 / 155 | 200 | 100 / 0 | 0.266 | 22.47 | 73.68 |

Across four candidate trials, ordinary probes returned 798/800
on time and 2 late; frequent probes returned 382/400
on time and 17 late, with 399/400 captured replies.
The baseline had 383/400 frequent replies on time and
17 late. Candidate download captures counted
1,086,170 unique source datagrams and
0 missing; upload counted
360,006 and 303 missing.

The upload exit's weighted CPU mean was
22.47% for the baseline and
22.74% for the candidate.
CPU means use accumulated busy ticks; peaks retain every nominal 250-ms sample.
Exit AWG peak RSS for the candidate was 68.47 MiB with
the same 96-MiB Go soft memory limit. These are bounded workload observations,
not a maximum-throughput test or a statistical CPU estimate.

## Admission losses exposed by the upload pair

The standard-profile upload pair lost 155 unique
UDP datagrams with the baseline and 303 with the candidate.
The early client guard counted 155 and
304 drops. In the candidate, the difference
is one ICMP request missing at the exit; no reply was generated for it.
These are forward-path admission losses, which reverse ciphertext recovery
cannot repair. They occur in both versions, so the v26 notification gate is
not their sole cause.

Before B confirms a new tuple to A, a 6000-packet/s client competes with admitted
noise for the unknown-traffic bucket. The measured profile has a 6000/s aggregate
rate and a 1024-packet burst. The source rate/burst remain 1500/s and 4096.
A further AB pair raises only the aggregate burst to 2048 with the same seed,
workload, WAN and movement. This adds room for 1024 unconfirmed packets while
keeping the sustained rate and source limit. It also admits a larger noise
burst. Recovery budgets and public profile defaults were not changed.

| Trial | Aggregate burst | UDP sent / missing | Early client drops | Frequent timely / late / captured | Exit mean CPU % | Peak VM CPU % |
|---|---|---|---|---|---|---|
| baselineburst2 | 2048 | 360001 / 0 | 0 | 100 / 0 / 100 | 23.95 | 80.00 |
| candidateburst2 | 2048 | 360001 / 0 | 0 | 100 / 0 / 100 | 22.55 | 78.95 |

In this diagnostic pair, all 720,002 unique source UDP datagrams arrived and
all 200 frequent probes returned within one second. The larger burst removed
the admission losses in these runs. These upload results do not establish a
fix for late download replies.

The laboratory rule tested in this diagnostic was:

```nft
limit rate over 6000/second burst 2048 packets counter drop
```

This small pair tests the hypothesis that discovery exhausts the shared burst;
it does not qualify the larger allowance against distributed noise or state
exhaustion. The 1024-packet default stays in place pending those checks.

Two earlier acquisitions claimed 2048 in controller metadata but still applied
1024: the string replacement expected an older 256-packet template. Their rule
hashes matched the standard profile. They are retained separately and excluded
from the valid comparison and totals. The corrected controller checks both the
rendered rule and the live nftables JSON before load. The two valid diagnostic
rows above passed that check; their rule hashes differ from the standard profile.

All 10 completed cases qualified noise and useful source rates within 1%.
They offered 17,500,000 noise datagrams. Queue/netlink, control
guard, netem, capture and switch-drop deltas were zero in measured windows.
Early client-guard losses in the standard upload pair are retained above.
No noise lease or duplicate plaintext was observed. Each trial required all
four lab Ethernet ports before and after measurement.

## What remains

The last-endpoint wait column includes the remaining recovery cooldown and
waiting for another fresh packet; it is not a direct measurement of the
notification gate. Approximate eligibility fields in the data subtract only
known endpoint availability and previous-attempt spacing. Journald and cross-VM
timing are approximate. Monotonic send duration and same-clock client capture
RTT remain separate. No per-packet causal trace was added to the hot path.

Seeded shaping does not give identical per-datagram delays: scheduling, batching
and packet grouping can change netem draws. The red/green regression establishes
the corrected condition; these few WAN trials do not establish a universal
latency improvement. A vanished NAT mapping and the time to authenticate a
new address and return a reply can still exceed the one-second budget.

Stock exit binary/unit/environment, original NAT/profiles and ordinary DNAT
were restored; both native probes passed before shutdown. All four guests and
owned seed/switch helpers are stopped; eleven loopback ports are free. Parent
disks, earlier reports/data and personal JSON match their initial hashes.
Production servers, the user's VPN, Windows networking and GitHub were untouched.

Keep recovery off on active servers. GUI clients, DPI, multiple moving peers,
distributed noise, state exhaustion and higher PPS/large packets remain untested.
Registered peers can still trigger bounded amplification without proof of
return reachability; repeated ciphertext remains linkable.
