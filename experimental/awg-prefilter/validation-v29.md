# v29: Holding forward packets during IP and NAT-port changes

English | [Русский](validation-v29.ru.md)

The optional holding queue preserved all 1,443,921 unique useful UDP packets
across four trials with 4 or 16 noise IPs. The paired v28-style admission
guard lost 2418 packets. Clients kept their native AWG binaries and profiles;
neither a fixed client IP nor a client-side helper was needed.

This is a lab result. During download, some replies still exceeded the
unchanged one-second ping deadline; the worst measured RTT was 1.983 seconds.
The queue and the existing return-recovery path remain experimental and off
by default. Normal installers were not changed.

## What changed

V28's moving client competed with noise for a shared admission budget before
B could confirm its new tuple. Increasing the initial burst did not reserve
capacity for that client. This candidate adds a small discovery allowance
and temporarily holds excess packets while waiting for the existing proof.

The aggregate budget stays 6000 packets/s with burst 2048: 5936/s and burst
1984 for bulk traffic, plus 64/s and burst 64 for the first packet of a new
conntrack flow. The first packet still passes the Header Protection filter.
An admitted first packet can establish tracking state; it does not authenticate
a client. Both bulk guards retain 1500/s with burst 4096 per source. Discovery
samples use their separate global allowance.

The separate [C process](flow-confirmation/escrow.c) retains packet IDs from
NFQUEUE 101. Linux keeps each original encrypted skb and conntrack reference;
the process receives at most 128 packet bytes and never rewrites the payload.
A's helper first installs the exit-confirmed kernel lease, then sends a
root-only Unix notification. Release requires the original source IPv4,
source port and conntrack ID to match. A separate nftables hook checks the
current kernel lease again after reinjection. B authenticates every VPN packet.

The optional [rules](flow-confirmation/escrow-rules.nft.example) require
conntrack accounting. Limits are one second, 32768 packet slots, 128 pending
flow identities, 4096 packets per identity and 8 MiB of wire bytes. Each lease
snapshot holds at most 128 records. Unsupported packets, expiration and
exhaustion fail closed. A stopped listener provides no queue bypass.
Build and VM setup are described in the [flow documentation](flow-confirmation/README.md).

## Test conditions

Four disposable QEMU/WHPX guests ran Debian 13 with one vCPU and 1024 MiB each,
without CPU quotas or a CPU threshold. A was the entry, B the exit, C held
two native clients and D generated noise. The v27 B binary, recovery bounds,
client profiles, noise generator and Ethernet switch were unchanged.
Return recovery was enabled in both profiles.

Each case sent 25,000 noise datagrams/s for 70 seconds, using 64 bound UDP
sockets across 4 or 16 IPv4 aliases on D. Sender counts matched independent
switch counts for every IP: 1,750,000 noise datagrams per case, 14 million in
total. Noise used a captured valid transport prefix and an unusable body,
with a 256-byte UDP payload. The aliases shared one NIC, MAC and burst scheduler.

Useful UDP requested 6000 datagrams/s with a 128-byte payload for 60 seconds,
about 6.14 Mbit/s of payload. Both directions were tested. The A-to-B path,
including mutual TLS, had 300-ms RTT and 30-ms jitter in each direction.
Netem queues held 16384 packets and had no configured random loss.
One client changed IP and NAT port three times; each next move began 250 ms
after the preceding gateway conntrack deletion ended. A second client stayed
stationary. Each case ran 100 ordinary probes per client and 100 frequent
probes at 50-ms intervals. Every probe kept its one-second deadline.

Four baseline/escrow pairs used equal seeds within each source-count/direction
pair, with varied order. Equal seeds do not reproduce identical packet timing.
The control used the tested v28 burst 2048; the public default remains 1024.
Conntrack accounting was enabled in both profiles. No compilation ran during
measurement. All CPU samples, capture hashes and counts are in
[results-v29.json](results-v29.json).

## Results

UDP loss is the set difference of unique inner datagram numbers captured
at sender and receiver. Ping columns show timely/late/missing replies out of
100 frequent probes. CPU columns are peak whole-guest samples from the trace.

| Noise IPs | Direction | Profile | UDP missing/sent | Ping timely/late/missing | A CPU % | B CPU % |
|---|---|---|---|---|---|---|
| 4 | upload | baseline | 1305/360001 | 97/0/3 | 44.00 | 45.16 |
| 4 | upload | escrow | 0/360001 | 100/0/0 | 50.00 | 39.29 |
| 16 | upload | baseline | 1113/360001 | 93/2/5 | 45.83 | 40.74 |
| 16 | upload | escrow | 0/360006 | 100/0/0 | 50.00 | 38.46 |
| 4 | download | baseline | 0/362209 | 95/5/0 | 41.67 | 78.12 |
| 4 | download | escrow | 0/361666 | 86/14/0 | 52.00 | 72.00 |
| 16 | download | baseline | 0/362105 | 90/7/3 | 41.67 | 65.00 |
| 16 | download | escrow | 0/362248 | 94/6/0 | 48.00 | 72.00 |

The candidate released 2581 held packets through a current kernel lease.
No noise tuple received an authenticated lease or used the trusted path.
No queue-capacity, netlink-socket, capture, switch or netem drops occurred in
the final matrix. One early client packet was discarded in the 16-IP upload
case; no useful UDP datagram or measured probe was missing in that case.
The candidate therefore preserves the measured useful stream, without proving
that every camouflage or control packet survives.

Iperf's inferred loss was nonzero in several zero-loss captures because
arrival order changed. Those figures are retained in the data; the table
uses unique delivery. The candidate delivered all 400 frequent probes,
including 20 late replies, and all 800 ordinary probes, including three late
replies. The control missed 11 frequent probes and one ordinary probe. Its
14 late frequent replies and two late ordinary replies are counted separately.
Some download delays were worse with escrow. This is not a latency guarantee.

A's weighted CPU means rose from 16.96-19.26% in the controls to 28.11-28.58%
with escrow; its highest sample was 52%. Across all candidate guests the
peak was 82.76%. The additional process used one thread and reached 2676 KiB
RSS/HWM. At most 25121 packets and 7,134,861 wire bytes (6.80 MiB) were held.
These figures exclude additional kernel skb/slab overhead; total peak kernel
RAM was not measured. All guests stayed within their 1-GiB configuration,
with no swap and no OOM events.

## Failure checks and corrections

`make check-escrow` passed the C self-check and nine Python helper tests.
The C self-check also passed AddressSanitizer and UndefinedBehaviorSanitizer.
It covers conntrack metadata, identity isolation, revocation, expiry and
packet, flow and byte limits. Python tests check optional activation, snapshot
encoding, private socket permissions and notification ordering after nftables.

Separate live NFQUEUE checks in the same isolated VM verified that a wrong
conntrack generation releases nothing; a root-injected stale snapshot is
blocked by the kernel recheck; and a matching current kernel lease releases
only the expected packets. Root-injected leases were used only for these
boundary checks, with the proof helper stopped. Expiry and process shutdown
dropped pending packets. A non-root sender was denied access to the socket,
and packets were dropped when the queue had no listener.

Two preliminary attempts are excluded from the final eight-case matrix.
The first process exited without a useful diagnostic. Queue socket handling
now attempts reception on `POLLERR`, counts `ENOBUFS` and logs unexpected
netlink types and kernel errors; the exact cause of that first exit cannot be recovered from
its log. The second attempt exposed a measurement assertion: it omitted
packets released around queue 100. Its residual 1362 exactly matched the
independent kernel release counter. The corrected accounting requires zero
unexplained packets, including released traffic. All final cases passed.

## Limits and next step

The queue also holds attack traffic. Larger packets, delayed proofs,
conntrack churn, more than 128 lease records, candidate-table exhaustion or
link saturation can still lose client traffic. Spoofing an already leased
tuple remains a way to consume B's authentication budget. Independent remote
noise hosts, IPv6, GUI clients, simultaneous moving peers, other kernels and
DPI behavior were not tested. Repeated return ciphertext and altered timing
still need a separate camouflage assessment.

The next useful test is a longer soak with independent noise schedules,
mixed packet sizes and repeated flow creation, while measuring kernel RAM
and tail latency. The current result supports further lab work; it does not
justify enabling this on an active VPN.

All four VMs and the owned switch/seed processes were stopped. Stock DNAT and
native-client probes passed before shutdown, and conntrack accounting was
restored. Parent disks, prior reports and personal JSON hashes were unchanged.
Production servers, the user's VPN and Windows networking were untouched.
Personal JSON and private packet captures are excluded from publication.
