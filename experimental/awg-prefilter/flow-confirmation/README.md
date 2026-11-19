# Exit-confirmed flow leases

English | [Русский](README.ru.md)

This experiment gives an authenticated client's flow a short kernel bypass
around the entry's shared unknown-traffic budget and NFQUEUE. Existing AWG
3.1 clients keep their applications, profiles and keys. Their public IP and
NAT port may change. Both servers need extra code; normal COLDWIRE installers
do not install or enable it. The [return-recovery study](../validation-v22.md)
adds an optional 500-ms history of B's encrypted replies. Six final trials
had no network UDP loss or late probes, with CPU recorded without a
threshold. The option is off by default; its repeated wire packets have
not been tested against DPI. The [deferred-recovery study](../validation-v24.md)
adds one bounded pending snapshot for fast moves. The
[successive-move study](../validation-v25.md) preserves and merges it across
attempts. The [late-response study](../validation-v26.md) adds send timing,
a GSO-friendly workspace and a tested individual-send fallback.
The [notification timing study](../validation-v27.md) removes a separate wait
for the next local notification before checking an eligible recovery. The preceding
[boundary study](../validation-v23.md) tests larger RTTs and delayed discovery.
Earlier results are in the [300-ms follow-up](../validation-v21.md),
[original WAN tests](../validation-v20.md), [local-link mobility tests](../validation-v19.md)
and [v18 measurements](../validation-v18.md).

## How admission works

The [v40 queue study](../validation-v40.md) splits holding between two queues
in one process. Queue numbers stay attached to packet IDs; all holding and
probe budgets remain shared. It addresses the per-queue kernel ceiling
identified in v39 without changing clients.

The [v39 timing study](../validation-v39.md) adds one early probe after the
nonce request has been written, with an ACK-gated fallback. Early probes use
a 32/s sub-budget within the unchanged aggregate limit. B still requires a
fresh authenticated event after receiving the query. The study also records
a lower kernel NFQUEUE ceiling than the configured packet bound.

The [v38 crash-recovery study](../validation-v38.md) keeps TLS connection and handshake work nonblocking. A continues draining candidate notices and maintaining kernel leases while reconnecting; B keeps the current authenticated stream until a replacement is verified. TCP/TLS setup has a two-second deadline on A and a one-second deadline on B. A requests one bounded refresh of held-flow metadata after startup. This root-only `CWR1` request grants no traffic. C reannounces live identities in batches of at most 64 notices per pass for at most one second.

A failed local candidate notice stays pending while its exact flow has held
packets. C retries at most 64 pending notices per 100-ms pass and stops that
pass on a failed send. The cursor rotates between flows; repeated failures
coalesce in one bit per flow. Empty or expired flows clear that bit. The
startup refresh uses the same pending flag when a notice fails. These are
untrusted metadata notices, not proofs, leases or extra VPN probes.

A also limits cached untrusted observations to four per learned source IPv4. Live leases and authenticated hints retain priority. Rejected excess identities skip the conntrack lookup; accepted candidates, probes and grants still require exact-generation checks. Many clients behind one NAT share these untrusted slots.

B uses a private receive replay filter with a 16,320-counter window, derived from the pinned upstream implementation. It adds 1 KiB per keypair. Duplicate and counter-limit rejection remain enforced; the upstream 8,128-counter filter and client-boundary tests are unchanged. These finite limits do not guarantee lossless recovery at arbitrary PPS or after longer outages.

The [v36 control-recovery study](../validation-v36.md) fixes stale TLS
sessions, B's restarted monotonic clock, and loss of still-live flow
observations during an outage. The main header filter also tolerates a
kernel `ENOENT` for an individual verdict whose queued packet has already
disappeared. Other netlink errors still stop the filter. These changes do
not extend leases or change client profiles, keys or wire packets.

The [v35 latency study](../validation-v35.md) changes B's existing maintenance
period from 100 to 10 ms, preserving the 250-ms replay spacing. All 4,340,141
useful UDP packets and 1200 ping replies in 12 qualified trials arrived.
Three consecutive moves still produced RTT up to 1383.822 ms; the candidate's
single-move maximum was 687.638 ms. A's poll and C's expiry margin remain
100 ms. Ordinary installers do not enable this prototype.

The [v34 study](../validation-v34.md) adds an optional routed-bridge holding
path for first packets whose conntrack entry is unconfirmed at prerouting.
The bridge queue runs after L3 NAT and confirmation, then checks the original
tuple and current generation. It requires a lab network change and an atomic
lease mirror; ordinary installers remain unchanged.

The [v33 follow-up](../validation-v33.md) also lets the existing maintenance
loop consume an armed recovery after cooldown, without another client packet.
It adds a bounded probe from the holding queue after B acknowledges a nonce,
and short admission leases for valid reordered data. The current return
endpoint still follows the highest accepted counter. The study tests
conntrack headroom and rejects temporary `ASSURED` pinning through the
tuple-based kernel update API.

Upgrade the patched receiver, both agents, `escrow.c` and the escrow nftables
rules together in a disposable lab. The nonce acknowledgement, admission-only
event and probe mark depend on those components agreeing. Mixing revisions
can prevent confirmation or omit the probe's kernel limit. Normal installers
still leave this experiment disabled.

The [v32 admission study](../validation-v32.md) fixes a second-lookup race
and a missed scheduler wakeup, and changes local proof-event eligibility
from 50 to 10 ms. Ordinary trials delivered all unique useful UDP packets.
A deliberately deleted pending generation still loses its held packets;
the exact cause of v31's 659-packet loss remains unproved.

The [v31 latency study](../validation-v31.md) rejects shorter work-based
replay pacing. It increased intermediate replay work in the fast-move test;
tails around 1.6 seconds remain. The runtime keeps its 250-ms interval, with
a regression protecting coalescing. The rejected patch is a research artifact.

The [v30 follow-up](../validation-v30.md) removes global conntrack scans,
tests helper restarts and increases bounded recovery capacity for large
packets. Final trials delivered all useful UDP; some probes still arrived
after one second.
This remains a lab option, disabled in the normal installers.

1. A forwards an unknown flow through the bounded admission guard and the
   existing Header Protection/MAC1 filter. These checks do not authenticate
   a client.
2. B's patched AWG receiver sends a local event after successful transport
   decryption, replay checking and the inner source-address check. An
   authenticated keepalive can also produce an event. Handshake-shaped
   traffic and conntrack state cannot produce this confirmation.
3. A reads the original tuple, conntrack ID and translated source port with
   an exact conntrack GET. It asks B to confirm that port using a fresh
   random 128-bit nonce. B acknowledges receipt. B must observe another authenticated transport
   event after receiving the request. Both timestamps are compared on B's
   monotonic clock; this check does not need synchronized server clocks.
4. B replies over mutual TLS 1.3. A checks the nonce, deadline, event order
   and current conntrack mapping again. It installs a ten-second nftables
   lease for `original source IPv4 . UDP source port . conntrack ID`.
   Reordered data from an older endpoint can instead obtain a one-second
   recovery lease. It does not change B's return destination.
5. Active traffic can refresh the lease. A new ordinary lease shortens old
   leases for that peer to at most one more second. At most four flows per
   peer can overlap; the earliest expiry is evicted beyond that bound.
   Idle leases expire. Losing the control
   connection leaves existing leases valid only until their original expiry.
   It cannot refresh them. A stopped helper cannot prevent kernel expiry.

The IPv4 lab fixes the destination interface, address and VPN port in its
rules. This is not a general multi-destination connection cache. NAT port
translation is read from conntrack rather than inferred from a client's
source port.

A schedules known flows every 100 ms and applies an accepted confirmation to
nftables immediately. It discovers flows from B's authenticated port hints
and, with forward escrow, early root-only candidate notices from the holding
process. Candidates and hints start a challenge; neither grants a lease.
The exact mapping and generation are checked again when the proof arrives.
B can emit a fresh same-endpoint event every 10 ms;
the TLS stream uses `TCP_NODELAY`. B selects endpoints and ordinary proof events
by the greatest accepted transport counter in its current keypair, with
a fresh counter epoch on key rotation. Late valid data can still be
delivered, but cannot select an older endpoint. A separate `CWA1` local event
can prove first-time acceptance of reordered current-key data for a short
admission lease. Its event must still follow the nonce request. With return recovery
disabled, replies already sent to a vanished NAT mapping remain lost.

A receives a hash of B's authenticated peer public key, not VPN session
keys or client private keys. The control channel has separate certificates.
The private Unix datagram socket accepts root credentials and carries no
payload. Its notification format includes a monotonic timestamp, observed
source address/port, peer identifier and transport counter. B still checks
every forwarded VPN packet cryptographically.

If a nonce has no acknowledgement by its existing three-second deadline,
A reconnects the control channel. An acknowledged request without a data
proof expires normally; it does not itself force a reconnect. B authenticates
a replacement with mutual TLS before closing the previous stream. A failed
certificate leaves the old stream intact. A clears old pending nonces and
proof-order timestamps only after a new authenticated TLS session, so B can
restart its monotonic clock without making old session proofs reusable.

A keeps at most 128 observed mappings. After ten seconds it rechecks up to
sixteen old observations per pass with exact conntrack GETs. Only the same
live generation stays in the cache; a missing or replaced mapping is removed.
That cache check grants no trust. With escrow enabled, an acknowledged fresh
nonce may request the newest held-packet probe even without an earlier authenticated
port hint. C still checks the exact live generation, and probes share the
existing 64/s, burst-64 budget and transport-only bridge classification.
A lease still requires B's fresh cryptographic confirmation. Hints retain
their challenge priority and reserved slots.

## Bounds and security limits

The basic `lab-rules.nft.example` allows unknown traffic up to 1500 packets/s with burst 4096
per source IPv4 address, followed by a shared 6000/s budget with burst 1024.
The larger initial credits cover the measured wait for a moving flow's fresh
proof. They replenish at the same sustained rates and allocate no packet
buffer. A sufficiently long delay can still exhaust them.
After header inspection, unleased initiation/response/cookie messages have
a separate limit: 20/s with burst 8 per source IPv4, then 100/s with burst
16 in aggregate. This prevents the larger transport credit from also
flooding B's handshake processing. The class comes from the decoded AWG
message type, rather than packet length or a particular noise fingerprint.
The dynamic source set holds at most 4096 addresses and expires idle entries
after five seconds. Allocation failure drops new unknown traffic. This
prevents one source's many ports from multiplying its initial allowance.
It uses addresses learned from packets; no client-IP allowlist is needed.
Confirmed flows bypass both unknown-traffic budgets.

The lease set holds at most 4096 flows. Helpers bound pending requests to
128, issue at most sixteen requests per tick, expire requests after three
seconds and bound peer/history/stream state. Sixteen pending slots are reserved
for authenticated hints and lease renewals; other candidates may use at most
four slots per source IP. These are learned addresses, not an allowlist.
The observed-flow cache holds at most 128 mappings. B's hints have a shared
64/s, burst-16 limit. The C filter retains queue
4096 and grouped individual verdicts. Its copy range follows the exported
S/H parameters; default S=12 still needs 212 bytes. See the [base filter's
parameter format](../README.md). IPv6 outer transport is unsupported.

A lease admits a tuple, so it cannot authenticate every subsequent packet
on A. A sender able to spoof a currently leased IP and port can enter that
fast path until expiry. The lab reproduced this with one modified
ciphertext packet; B rejected it and it did not refresh the lease. An
abusive registered peer, on-path injection, source spoofing, distributed
sources and link saturation still need separate protection.

Clients behind one public IP share the unknown-source budget before they
are confirmed. New connections and changed tuples must obtain a new proof;
packet loss during that interval remains possible. V18 retains the original
transient losses; v19 compares the calibrated burst allowances against them
and checks cold starts.
Clients at one source IP also share the control-message allowance. Large
simultaneous client populations, set exhaustion and adaptive cookie/MAC2
attacks have not been tested.
The helper no longer dumps conntrack or clears leases when the global table
exceeds 4096 entries. V30 tested 8192 noise sockets. The kernel's own
conntrack capacity and memory remain finite, and the original prerouting path can still lose unconfirmed first packets
while discovery credits are exhausted. The optional bridge path is described below.

Unknown flows retain the strict filter's I1/Jc drops. An active lease
bypasses that filter for its tuple, including camouflage packets. Client
wire formats are unchanged; the resulting A-to-B camouflage has not been
validated against DPI.

## Optional forward escrow

The [v29 study](../validation-v29.md) tests a separate holding queue for packets
that exceed admission limits while A waits for B's proof. This requires the
new `escrow.c` process and `escrow-rules.nft.example`; the normal rules and
installers remain unchanged. Build and check it in the parent directory:

```sh
make check-escrow
```

In the disposable entry VM, enable `net.netfilter.nf_conntrack_acct=1` before
creating test flows. Create `/run/coldwire-escrow` as root with mode 0700 and
start `escrow --vm-test` before loading its rules. It accepts only hostname
`kit-entry` and binds queues 101 and 102 on one netlink socket. Add
`"escrow_socket": "/run/coldwire-escrow/grants.sock"` to A's private helper
configuration. Queue 100 and the original classification-enabled prefilter
remain in use. The helper must install its kernel lease before notifying
the holding process.

```sh
sudo install -d -m700 /run/coldwire-escrow
sudo ./flow-confirmation/escrow --vm-test
```

The example splits the existing 6000/s, burst-2048 aggregate allowance into
4976/s with burst 1024 for bulk traffic, 960/s with burst 960 for discovery,
and 64/s with burst 64 for forward probes. Samples still go through header inspection;
it cannot authenticate a client. Excess traffic enters queues 101/102, with no
queue bypass or fail-open option. Only confirmed IPv4/UDP conntrack entries
and individual IP packets up to 1536 bytes are eligible for holding.
Conntrack confirmation is kernel tracking state; it grants no VPN identity.

The lab can put discovery samples on their own NFQUEUE 103 so they can reach
the classifier while queue 100 is stalled. [V52 patch setup and measurements](../validation-v52.md#the-lab-patch)

Discovery also uses a learned per-source bucket: 32/s with burst 256,
at most 4096 addresses and five seconds of idle time. This prevents a few
sources repeatedly creating flows from taking the entire discovery budget.
Exhausted discovery credits fall back to the ordinary bounded guard. Many
sources can still exhaust the shared budget; this is not source authentication.
Discovery also covers reused NAT tuples whose conntrack entry is still alive;
requiring `ct original packets 1` would miss them.

After the TLS output buffer drains, A may request one early held packet on
its next maintenance pass. `CWT1` limits these early probes to 32/s with burst
32, within C's existing shared 64/s, burst-64 probe budget. The request can
still arrive at B after its UDP probe. Such a pre-query event cannot prove a
flow; after B acknowledges the nonce, A may request one `CWS1` fallback.
A rechecks the exact conntrack generation and skips probes for live leases.
Both root-only requests expire within one second and grant no lease.

The local `0x04000000` mark also passes a separate 64/s kernel limit. Queue
100 checks the header and B authenticates the transport packet. Prerouting
probes clear this mark before classification. A valid post-query event can
recover packets from a NAT mapping the client has already left. Duplicate or
invalid ciphertext cannot provide that event. Full budgets, expired holding
packets and missing mappings still prevent recovery. Update the agent and C
holding binary together. [V39](../validation-v39.md) records the timing and
failure controls; the earlier v34 early-probe experiment remains rejected.

The process keeps kernel packet IDs and metadata, with an 80-byte packet
copy in each netlink message. This covers a 60-byte IPv4 header, UDP and the
12-byte transport nonce. Conntrack attributes and netlink overhead are
additional. The shared receive-buffer request is 20 MiB (40 MiB as
reported by Linux). Linux retains the original encrypted skb and its conntrack reference.
Bounds are 2.6 seconds, 131072 packets, 8192 pending flow identities, 16384
packets per identity and 32 MiB of wire bytes. A salted hash table replaces
the linear flow search. Kernel skb overhead is additional;
the byte limit is not a total-RAM limit. Expired or excess packets are dropped. The packet bound is shared
by both queues. Each kernel queue is configured for 65536 pending packets;
C keeps one global packet ring and one set of byte, flow and probe budgets.
A packet's identity includes its queue number, because two queues can issue
the same packet ID. Its verdict returns to that exact queue.

The rules alternate packets with `queue to numgen inc mod 2 offset 101`.
A plain queue range hashes IP addresses on this kernel; NAT makes the bridge
packets share those addresses, so a range can send them all to one queue.
One process drains both queues. There is no bypass if either listener is
missing. Update C and both rule examples together. [V40](../validation-v40.md)
records the capacity test, wrong-queue and missing-listener controls, and
native-client measurements. This does not extend the 2.6-second holding limit.

A root-only Unix socket receives up to 128 lease records per snapshot for the exact source
IPv4, source port and conntrack ID. On release, the next nftables hook checks
that identity against the current kernel lease again. The local mark
`0x08000000` requests this check and is cleared on physical ingress. It is
never carried on the wire. B still authenticates every forwarded packet.
The [NFQUEUE API](https://netfilter.org/projects/libnetfilter_queue/doxygen/html/group__Queue.html)
provides conntrack metadata; Linux resumes an accepted queued packet at the
[next netfilter hook](https://github.com/torvalds/linux/blob/v6.12/net/netfilter/nfnetlink_queue.c#L292-L348),
so this recheck uses a separate base chain.

Holding adds latency and retains attack traffic too. It cannot guarantee
delivery after its bounds are reached or before a proof arrives. Tuple
spoofing, conntrack churn, excessive candidate counts and link saturation
remain limits. This path has no GUI-client or DPI validation. For rollback,
stop A's helper while its table exists, remove the experimental table, then
stop both queue processes. Restore the saved conntrack-accounting setting
after the experiment. A missing queue listener drops matching traffic.

The helper resends its current lease snapshot every 250 ms without extending
any deadline. C's encoded grant expires one polling interval (100 ms)
before the agent's lease. Packets near expiry can wait for a fresh snapshot
instead of being released against an already expired kernel set. This margin
does not make kernel and process expiry atomic under long scheduling stalls. A structurally valid snapshot discards expired records and
keeps its live records; invalid identities, duplicates, zero deadlines and
excessive future deadlines still reject the snapshot. The holding process can replace an orphaned root-owned 0600
socket after a crash; it refuses a live socket, regular file or symlink.
The three `coldwire-*.service.example` files provide restart settings for
the disposable `kit-entry` and `kit-exit` hosts only. They are not VPS units
or an installer. V30 tested their automatic restarts and control-channel
expiry with native clients; it did not test failure under a saturated link.
An `ENOENT` reply to this process's queue-101 or queue-102 verdict is counted rather than
stopping all forwarding: the kernel has already removed that packet. Other
netlink errors remain fatal. V30 exercises this with a real hook reload.
Packets discarded by a hook change remain lost.

### Optional holding after conntrack confirmation

The [v34 bridge rules](escrow-bridge.nft.example) add a lab-only alternative
for an overflow packet whose entry is still unconfirmed. Create the routed
`cw34br` bridge with physical `enp0s3` as its port, move the lab address and
matching L3 interface rules to that bridge, and preserve management access
on the separate lab NIC. These names and addresses belong to the disposable
lab. Do not copy the network changes onto a working VPS.

Load the bridge table and its final `unconfirmed` chain replacement in one
nft transaction. Then enable `"late_escrow": true` alongside the canonical
`escrow_socket` in A's root-only config. Use the matching current C process,
agent and both escrow rules files. The agent installs IPv4 and bridge leases
in one transaction before notifying C. A failed install gives no C grant.

Marked excess packets skip header classification while waiting. The bridge
queue runs after L3 NAT/confirmation; C validates its family, hook, confirmed
non-dying ID, original/reply tuples and actual SNAT addresses. A separate
bridge chain checks the current lease again before release. Untrusted probes
still pass queue 100's header filter. Bridge probes carrying control messages
are dropped, so this path adds no handshake allowance. C shares one 64/s,
burst-64 probe bucket across both holding paths. Other holding limits stay
the same. This changes neither client profiles nor B's receiver.

For rollback, stop A's helper while both tables exist, restore the original
unconfirmed-chain rule and remove the bridge table, then restore the saved
lab address/interface rules. Remove the admission tables before stopping
queue listeners. Missing generations, exhausted conntrack capacity or the
one-second holding deadline can still lose packets. The bridge path has
only been tested on the Debian 13 lab kernel in v34.

## Optional return recovery

The patched binary includes a separate lab option, disabled by default:
`COLDWIRE_LAB_RETURN_REPLAY=1`. It also requires the existing
`COLDWIRE_LAB_PROOF_SOCKET` setup. Installers do not enable either option.

Recovery can produce bursts large enough to fill the client's UDP receive buffer.
An optional lab queue on A smooths those bursts and adds queueing delay during recovery. [V53 setup and measurements](../validation-v53.md#return-path-pacing)

On the disposable exit VM, `COLDWIRE_LAB_RETURN_SETTLE=1` enables the v55
option alongside return replay. It coalesces successive authenticated moves
and makes recovery eligible sooner when the ciphertext cache advances by
7,400 entries. The experiment also enlarged the exit's `awg0` transmit
queue to 2,048 packets. [V55 lab setup and measurements](../validation-v55.md#the-2048-packet-queue-on-b)

B copies outbound encrypted transport packets into a shared ring. The ring
holds at most 8192 packets and 8 MiB of ciphertext, plus fixed metadata.
Only packets younger than 500 ms are eligible; an idle cleanup runs every
10 ms. It stores a hash of the peer's public key and scalar keypair epoch
fields, without retaining plaintext, session keys or keypair pointers.

After a fresh, source-policy-valid transport packet selects a changed
endpoint, B commits that endpoint before taking the recovery snapshot.
The sender records each encrypted packet before reading its destination,
so packets created after the snapshot already use the new path. B can
resend this peer's current-epoch ciphertext towards it.
An immediate selection takes at most 8192 packets and 8 MiB, in original
order. A merged deferred snapshot can reach 16 MiB within the shared
8192-packet pending limit. The earlier per-attempt 8-MiB claim was incorrect.
There is at most one attempt per 250 ms per peer, including empty immediate
lookups, and one nonempty attempt per 250 ms globally. Only one send can be
in progress. Ordinary endpoint updates continue while recovery waits.
Clients use their existing replay filter to discard copies already seen.

Each fresh, source-checked current-key packet can check a pending recovery,
including packets between the 10-ms local notifications. Recovery keeps its
own 250-ms per-peer and global spacing. The client wire format is unchanged;
no timer or worker was added. Sparse traffic can delay a proof beyond the
notification interval, since it requires a fresh authenticated packet.

Recovery copies one current batch into a reusable contiguous workspace.
This gives the standard bind room for UDP GSO coalescing while keeping the
retained ciphertext intact. The workspace is temporary and bounded by the
current batch, at most the 16-MiB pending-snapshot budget. A successful individual-send
fallback after GSO is disabled continues with the remaining batches; a failed
fallback stops the attempt. Both paths are tested.

After an immediate attempt, B retains the selected ciphertext without another
payload copy. Stationary traffic cannot rearm it. A move blocked by cooldown
or a busy sender can also create a pending snapshot from the ordinary ring.
All retained snapshots together hold at most 16 peers, 8192 packets and 16 MiB.
They contain ciphertext, the peer-key hash, scalar key epoch/order fields
and an address string. A bounded reference to the owning peer lets the
maintenance loop read its current key and endpoint; the snapshot stores no
keypair pointer. The reference expires with the snapshot. A fresh
authenticated move retargets the snapshot
and appends newer eligible replies from the ring within those same budgets.
A local insertion sequence prevents overlap from being copied twice.

After cooldown, a fresh transport notification or the existing 10-ms
maintenance loop can make one deferred attempt for an armed move. Its
source-policy check must already have passed; the current key and endpoint
must still match. A stopped peer, closed device or disabled roaming prevents the retry;
each send batch checks the current key and endpoint again. Already submitted
network packets cannot be recalled. After an attempt, the snapshot becomes
unarmed and remains available for another fresh move until its original
1100-ms deadline. Retargeting and sending never extend that deadline.
The same tick releases idle snapshots. Receiver and maintenance attempts
share a per-peer mutex and the existing global sender lock. No new timer or
worker was added. The loop cannot arm a stationary snapshot or invent a new
destination. A busy sender or the original expiry can still prevent recovery.

The ordinary ring still selects only packets younger than 500 ms. A retained
snapshot can outlive that ring; newer replies are added only on another
authenticated move. The [v25 report](../validation-v25.md) compares the changes
with v24 and records the remaining delivery and deadline limits.

The [boundary study](../validation-v23.md) used the earlier 4096-packet limit;
[v24](../validation-v24.md) added a frozen pending snapshot. V25 preserves
and merges snapshots across attempts. V30 raises the attempt budget to 8 MiB
and the global pending budget to 16 MiB so large packets can use the slot
budget across successive moves. Neither change extends a deadline or enables
recovery without a fresh authenticated move. The cache is shared between peers, so
another peer can evict recent replies.
The helper also uses a one-second
TCP connect and server TLS-handshake timeout; startup at RTT 1400 ms failed
in the lab. Longer-timeout raw TCP success does not establish mTLS support
at that RTT.

Recovery can miss old packets, key changes, frequent or concurrent moves,
cache eviction and packets outside the client's replay window. It adds
traffic during movement. A registered peer that can send valid transport
can also trigger bounded retransmissions; the limits do not establish
return reachability. Repeated ciphertext is visible on the wire, so this
option has no DPI or unlinkability guarantee. Leave it disabled on active
servers while evaluating these tradeoffs in the lab.

## Files and local checks

| File | Purpose |
|---|---|
| `agent.py` | B's authenticated-event receiver and A's conntrack/lease controller |
| `conntrack.py` | Exact original/reply tuple GET with generation and kernel-origin checks |
| `test_conntrack.py` | Netlink encoding, identity, malformed reply and error tests |
| `lab-rules.nft.example` | Combined unknown-source/aggregate guard, lease lookup and queue hook |
| `escrow.c` | Bounded held packet IDs, confirmed-generation metadata and shared probe budget |
| `escrow-rules.nft.example` | Prerouting holding and the kernel lease gate |
| `escrow-bridge.nft.example` | Optional holding after confirmation and bridge probe classification |
| `coldwire_proof_linux.go` | B's authenticated notification and counter-ordered endpoint selection |
| `coldwire_return_linux.go` | Optional bounded ciphertext cache and authenticated-move retransmission |
| `patch_awg.py` | Patches and formats the pinned Linux receiver, including its private replay filter |
| `coldwire_replay_linux_test.go` | Server/client replay-window boundaries, duplicate rejection and reset |
| `test_agent.py` | Freshness, replay, movement, bounds, streams and immediate kernel-update tests |
| `coldwire_proof_linux_test.go` | Event format/rate, endpoint reorder, key rotation and snapshot-handoff tests |
| `coldwire_return_linux_test.go` | Cache isolation, expiry/capacity, replay bounds and encrypted recovery/duplicate tests |
| `coldwire_return_boundary_linux_test.go` | Exact age, shared-cache eviction, byte-budget order and pinned client replay-window boundaries |
| `coldwire_return_deferred_linux.go` | Bounded pending snapshots and a retry on fresh authenticated transport |
| `coldwire_return_deferred_linux_test.go` | Retargeting, expiry, budgets, runtime guards, concurrent cleanup and encrypted recovery |

From this directory:

```sh
python3 test_agent.py
python3 test_conntrack.py
```

The patcher requires Go's `gofmt` on `PATH` and accepts only clean AWG commit
`1b86b2ae0e493e7ea93f8c1a0f0cb6735b1551f1`. It refuses a second application.
In a disposable Linux source checkout, run:

```sh
python3 /path/to/flow-confirmation/patch_awg.py /path/to/clean/amneziawg-go
cd /path/to/clean/amneziawg-go
go mod verify
sudo env GOMAXPROCS=1 go test -p 1 ./... -count=1
env GOMAXPROCS=1 GOMEMLIMIT=384MiB GOGC=50 CGO_ENABLED=0 go build -p 1 -trimpath -ldflags='-s -w -buildid=' -o amneziawg-go-proof .
```

V37 used Go 1.25.12; the rebuilt v38 lab used Go 1.25.0. The notification is inserted in the
[pinned receive path](https://github.com/amnezia-vpn/amneziawg-go/blob/1b86b2ae0e493e7ea93f8c1a0f0cb6735b1551f1/device/receive.go)
after transport authentication and source-policy validation. Do not use
this patch with another source revision without reviewing those checks.

## Disposable-lab setup

The helpers deliberately require root, hostnames `kit-entry`/`kit-exit`,
private IPv4 endpoints and `--vm-test`. They are not production services.
Use a lab that already has working DNAT/SNAT, two native AWG clients and the
[C prefilter](../README.md). Keep original binaries and service definitions.

Provide Python 3, nftables and OpenSSL. Place `agent.py` and `conntrack.py`
together on both hosts. The `conntrack` CLI remains useful for lab setup and
diagnostics; the helper uses netlink directly. Place
each helper's config and its private key in a root-only directory, with mode
0600 on both files. The config has these fields; use the role's own
certificate/key and the other role's pinned certificate as `ca`:

```json
{
  "entry": "192.168.76.10",
  "exit": "192.168.76.20",
  "vpn_port": 32497,
  "cert": "/root/flow-confirmation/entry.pem",
  "key": "/root/flow-confirmation/entry.key",
  "ca": "/root/flow-confirmation/exit.pem",
  "events": "/run/coldwire-flow/events.sock",
  "status": "/root/flow-confirmation/entry-status.json"
}
```

The measured lab used separate, short-lived Ed25519 certificates with the
correct IP SAN and client/server authentication usage. B listens on TCP
39101 and accepts only A's address plus its client certificate. A verifies
B's IP against the pinned server certificate. Test rejection without a
client certificate before applying packet rules.

Create `/run/coldwire-flow` as root with mode 0700. Start B's helper first:

```sh
sudo python3 agent.py --vm-test exit /root/flow-confirmation/config.json
```

Start the separate patched AWG binary with
`COLDWIRE_LAB_PROOF_SOCKET=/run/coldwire-flow/events.sock`. The listener may
start later or restart: subsequent authenticated notifications check the
current root-owned 0600 socket again. Keep the original AWG binary intact.

On A, use the classification-enabled C variant on queue 100. Build it in the parent
directory with `make check-handshake`, then run `prefilter-handshake` with
the same key file and `--vm-test --queue 100` arguments. The original
`prefilter`/`prefilter-batch` builds still serve the C-only examples.

The variant adds local netfilter metadata after inspection: `0x40000000`
means classified and `0x20000000` identifies control messages. It preserves
unrelated mark bits and returns no replacement payload. These marks are
absent from wire packets. The C variant uses the
[NFQUEUE verdict metadata API](https://netfilter.org/projects/libnetfilter_queue/doxygen/html/group__nfq__verd.html).
The holding parser still bounds IPv4 packet length to 1536 bytes; larger
wire packets are outside this combined experiment, even when the base header
parser accepts their parameters. The lease path reserves `0x10000000`; the
example clears all three reserved
bits on ingress. An older unmarked classifier
fails closed in the combined rules; check that drop counter when debugging
a mismatched binary/ruleset.

Check and load the combined
`lab-rules.nft.example`, replacing existing experimental guard/queue tables
in one nftables transaction. Do not leave the older queue hook active.
Keep the relay's ordinary NAT table. Arm a rollback timer before loading
rules, then start A's helper:

```sh
sudo python3 agent.py --vm-test entry /root/flow-confirmation/config.json
```

A requested SIGTERM/SIGINT stop keeps already confirmed kernel/C leases until
their existing deadlines, at most ten seconds. This avoids flushing live
traffic on a helper restart. Its root-only status file also records the boot
ID, relay scope and absolute monotonic deadlines. On startup A restores only
the intersection with both live kernel sets, then verifies each exact
conntrack generation. Restoration never issues a new proof or restores old
nonces, hints or proof-order timestamps. The same file keeps up to 128 observed
candidates for a fresh challenge after restart. Their original observation
ages and exact conntrack generations are checked; they restore no lease or
authenticated-hint priority. Missing, invalid, stale or
other-boot cache data gives no restored lease. A fatal error in the running
loop still
clears its leases; a crash cannot keep them beyond kernel expiry.

This covers a helper restart within one kernel boot. Rebooting the whole A
VM destroys conntrack and interrupts its network; it needs fresh proofs.
Stopping the helper alone no longer revokes fast-path grants immediately.
To revoke those grants, stop A and atomically flush both `trusted` sets
while keeping the guard rules loaded. C replay is rechecked against those
sets. A full rollback removes the experimental guards and returns ordinary
DNAT forwarding.

Both status files report connection state and bounded counters. A also
records grants, expiry and replaced tuples. Measure early client discards,
NFQUEUE loss, useful throughput, probe delivery and whole-VM CPU together.
[V37](../validation-v37.md) tests configurable wire parameters and helper-restart continuity.
[V36](../validation-v36.md) tests control recovery and vanished NFQUEUE verdicts.
The [v29 study](../validation-v29.md) tests bounded forward escrow under
multi-IP noise. [v28](../validation-v28.md) compares admission bursts.
[v27](../validation-v27.md) tests recovery independently of
notification sampling. [v26](../validation-v26.md) separates late-response
timing and submission cost. [v25](../validation-v25.md) studies repeated-move recovery.
[v24](../validation-v24.md) records the corrected lab NAT model.
[v23](../validation-v23.md) records the separate
startup limit. The [v22 study](../validation-v22.md) contains
the original recovery controls and measurement corrections. Earlier admission and
cold-start controls are in [v19](../validation-v19.md).

For rollback, stop A's helper while its table still exists, remove the
combined experimental IPv4 and optional bridge tables, then stop the C filter.
Restore B's original
AWG service command and environment, restart it and reconnect the two lab
clients. Stop B's helper and confirm ordinary DNAT probes. None of these
steps belongs on an active server as part of this experiment.

Removing the lab bridge can change A's MAC address. Expire its stale ARP entry on the other lab VMs before checking ordinary DNAT.
