# V33: fresh admission proofs and quiet-client return recovery

English | [Русский](validation-v33.ru.md)

The prototype now handles a missed admission-proof window and can run an
already armed return retry without waiting for another client packet. A third
fix lets the holding process accept live leases when another record in the
same snapshot has expired. Five final qualified trials delivered all
1,801,822 unique useful UDP packets. Some ping replies still took up to
1677.096 ms. An earlier probe version lost one UDP packet at an unconfirmed
conntrack entry; that failure mode remains unresolved.

These changes stay in the experimental directory. Normal installers are
unchanged. The study used four isolated local Debian 13 VMs, each with one
vCPU and 1024 MiB RAM, without a CPU limit. No existing VPN or remote server
was changed. Full measurements, source hashes and rejected acquisitions are
in [results-v33.json](results-v33.json).

## Why a moving client's queue expired

The scheduled-return-only trial `sch-collision-trace-lean128u-r2` lost 402
unique UDP packets and one ping. All 403 held packets for its first moving
flow expired. B had authenticated 12 packets from that translated port,
but every event preceded receipt of A's nonce request. The last was
55.478 ms too early. No eligible event followed the request, so the agent
correctly refused to authorize the queue.

This identifies a failure of a short-lived route to produce a fresh proof.
Aggregate conntrack eviction counters also increased, but the traces do not
prove eviction of this particular generation. They cannot establish the
exact cause of the historical 659-packet loss in v31 either.

The retained fix has three parts:

* B acknowledges receipt of the nonce over the existing mutual-TLS channel.
  Once A also has an authenticated port hint and an exact current-generation
  conntrack match, it may request one held packet as a forward probe. A skips
  flows with a live lease and sends at most one request per nonce.
* B may report first-time acceptance of reordered, current-key transport
  through a separate local `CWA1` event. Decryption, replay protection and
  inner source policy still apply. The event can authorize a one-second
  admission lease; it cannot select an older return endpoint or replay
  replies. Endpoint selection still follows the greatest accepted counter.
* A new ordinary ten-second lease leaves previous flows of that peer up to
  one more second to drain. At most four flows overlap; excess entries lose
  the earliest expiry. A recovery-only proof does not shorten a live
  ordinary lease.

The root-only `CWS1` request has a one-second deadline and grants no lease.
The held packet receives a local probe mark, passes a 64/s, burst-64 kernel
limit and the normal header filter, then still needs B's cryptographic
acceptance. The mark is cleared before classification. The aggregate unknown
allowance remains 6000/s with burst 2048: 4976/1024 bulk, 960/960 discovery
and 64/64 probes. Holding bounds and generation checks remain unchanged.

One final trace contains a fresh recovery event for the departed first
route 404.866 ms after B received the query; A confirmed its current
generation 447.761 ms after requesting the probe. The data includes that
join. Other probe requests met proofs already in flight, so request counts
alone do not establish that a probe caused recovery. The last trial checks
the current agent's live-lease suppression: nine root requests produced two
actual probes, with all 360,001 useful UDP packets delivered.

Upgrade B's patched receiver, both agents, the holding process and its
nftables rules together in a disposable lab. Their new event, acknowledgement
and probe handling depend on each other. Clients keep their binaries,
profiles, keys and ports; NAT changes happen on the lab gateway.

## Return retries and snapshot expiry

The existing 100-ms maintenance loop now consumes an eligible armed return
snapshot when the client is quiet. It uses the current key and matching
current endpoint. A per-peer mutex protects the shared send state against
the receiver. No new worker or timer was added. The 250-ms replay spacing,
1100-ms pending expiry and bounds of 16 peers, 8192 packets and 16 MiB remain.
A pending entry holds a bounded peer reference and releases it at expiry;
it retains no keypair pointer. A stationary snapshot cannot rearm itself.

The C holding process previously rejected an entire root snapshot if one
lease expired between construction and receipt. It now validates the whole
message, rejects malformed identities and duplicates, and filters expired
nonzero records while retaining live ones. A regression test fails with
the old behavior. Final trials exercised this filter without a malformed
snapshot rejection. The earlier single `control_bad` observation is not
enough to prove that expiry caused that particular rejection.

## Measurements

Noise was 25,000 packets/s from 16 IP addresses; useful UDP was 6000/s.
VPN and control paths both had nominal RTT 300 ms and normal jitter of
30 ms per direction. Each run made three IP and NAT-port changes, at
requested gaps of 250 or 100 ms. Upload tests used 128-byte useful payloads,
8192 noise flows and forced SNAT-port collisions. Download tests used
1200-byte payloads and 64 noise flows.

There were 19 qualified trials across four source stages. Qualification
requires exact per-source sender/switch noise counts, matching aggregate
arrival at A, rates within
1%, and zero switch, capture and WAN-emulator drops. Useful loss is counted
from unique sequence IDs at both ends after draining, independently of
iperf's provisional loss report. Native clients were unchanged; no noise
flow received a lease or reached the trusted path in any qualified trial.

Final results:

| Case | Useful UDP delivered/sent | Ping replies after 1 s, of 100 | Maximum RTT |
| --- | ---: | ---: | ---: |
| Fast moves, table 8192 | 360,001/360,001 | 0 | 972.034 ms |
| 250-ms moves, table 8192 | 360,004/360,004 | 2 | 1112.666 ms |
| Fast moves, table 16384 | 360,004/360,004 | 5 | 1267.536 ms |
| Download, table 8192 | 361,812/361,812 | 11 | 1677.096 ms |
| Fast moves, current agent guard | 360,001/360,001 | 1 | 1067.620 ms |

All 500 ping replies eventually arrived; 19 missed the one-second deadline.
The first four rows precede the final live-lease probe suppression; the last
uses the exact current agent. They share the final receiver and C behavior.
Mean whole-VM CPU in these rows was 30.38 to 36.26% on A and 33.57 to 68.64% on B.
Jitter and host scheduling differed between acquisitions, so those CPU
figures are observations, not a controlled speedup measurement.

Two matched-workload download controls had 21 late replies out of 200,
with maxima 1702.990 and 1562.467 ms. Scheduled-return-only trials had 22
late replies, with maxima 1554.350 and 1672.768 ms. Thus the encrypted
quiet-client test proves removal of the extra packet dependency, but the
paired trials do not demonstrate an overall tail-latency improvement.
In the latter 1672.768-ms example, the final NAT change completed 904.890 ms
after the ping request; B's inner request-to-reply interval was 11 µs.
The client timeline and B's interval each use a single VM's clock. Multiple
moves, delayed path discovery and return travel still consume time.

Raising A's conntrack capacity to 16384 in selected lab trials removed
their `early_drop`, `drop` and `insert_failed` increments; the observed peak
was 9576 entries. An 8192-entry table competed with 8192 noise flows.
Extra headroom is finite and is not client authentication. No installer or
sysctl default changed; the lab was restored to 8192.

Three acquisitions were excluded from comparison and kept in the data:
one control had 23,069 switch drops and lost 5036 unique UDP packets; one
run missed seven noise packets before the switch but delivered all useful
UDP; another missed 1502 noise packets before the switch and lost 495 useful
UDP packets. Their causes are not established. A qualified repeat does not
erase those failures or prove that host activity caused them.

## Rejected shortcuts and remaining limits

The initial fast probe trial lost one unique UDP packet because its
conntrack entry was still unconfirmed. Two bounded rescue experiments were
rejected: the late postrouting generation gate rejected even the positive
case, and Debian's kernel rejected conntrack expressions at netdev egress
during `nft -c`. All rescue code and optional configuration were removed.
The retained process still drops unconfirmed entries. The five final
zero-loss runs do not prove this race has disappeared.

Temporary `ASSURED` pinning was also rejected. On Debian kernel 6.12.116,
a tuple-based UPDATE carrying the wrong ID still set `ASSURED`; clearing
it returned `-EBUSY`. A wrong-ID DELETE returned `-ENOENT` and preserved
the generation. The experiment touched only one exact lab noise flow and
removed it afterwards. The API behavior is consistent with the upstream
[conntrack netlink implementation](https://github.com/torvalds/linux/blob/v6.12/net/netfilter/nf_conntrack_netlink.c).
Eviction policy can be inspected in
[conntrack core](https://github.com/torvalds/linux/blob/v6.12/net/netfilter/nf_conntrack_core.c).
An unclearable status update without the required generation check is not
retained as a protection mechanism.

Full conntrack tables, missing generations, shared-budget exhaustion and
the finite one-second holding window can still lose packets. Response time
is not bounded by one second. This study does not validate GUI applications,
IPv6, DPI resistance, production operation or a new long soak. Server-side
changes preserve client formats; they do not prove unchanged camouflage.

## Checks and reproducibility

The clean pinned AWG source passed 39 top-level Go tests, with two upstream
skips, and the Coldwire race tests. Tests include real encrypted recovery
without another client packet, concurrent receiver/maintenance activity,
endpoint monotonicity, rejection of stale-key admission and bounded replay.
The final ELF matches the measured candidate. The entry passed 19 agent and
five conntrack tests. C self-tests passed normally and under ASAN/UBSAN,
including a regression that fails with the old snapshot-expiry behavior.

The data records each trial's actual source stage. For scratch reconstruction
from commit `405c5450e2cc04cb8b3d8c62869e1fb889a6f53b`, apply these research
artifacts in order: [retained v32 source](research/v32-retained.patch),
[scheduled return only](research/v33-scheduled-only.patch), then
[initial forward probe](research/v33-initial-forward-probe.patch).
Each stage was reconstructed byte for byte. They are historical research
artifacts, not deployment patches. Current source hashes identify the final
variant, including the live-lease guard and snapshot filter.

Both original native profiles passed ordinary-DNAT probes after restoration.
The four VMs and owned switch/seed helpers are stopped; all eleven lab
loopback ports are free. Parent disks, earlier reports including v32, and
ignored personal JSON files remain unchanged. No local commit or GitHub
push was made.
