# Recovering replies after a NAT move

English | [Русский](validation-v22.ru.md)

Test date: 14 November 2026. The final 500-ms recovery build passed six
qualified trials: all 2,164,522 useful UDP datagrams reached the other end
of the tunnel, with no plaintext duplicates. Ordinary probes received
1200/1200 replies and frequent probes 600/600 within their one-second
deadline. The two comparable reverse-UDP controls without recovery lost
1817 and 1910 datagrams at the NAT move. See [data](results-v22.json) and
[the preceding study](validation-v21.md).

This stage records CPU without an acceptance threshold. All guests still
have one vCPU and 1024 MiB RAM; no runtime or build CPU quota was used.
The final peak was 95.83% on the client VM. The prototype is disabled by
default and remains separate from the normal installers.

## Setup and acceptance

Four fresh Debian 13 COW guests ran kernel 6.12.116 under QEMU 11.1.3/WHPX.
A is the entry, B the exit, C the client gateway and D the noise source.
The two native AWG clients retained their binaries, keys, profiles and
ports 32497/32498. Only C's gateway changed profile 1's source IP, or its
IP and NAT port, 25 seconds after workload launch. No permanent client-IP
allowlist was used.

Every counted trial offered 25,000 noise datagrams/s for 70 seconds from
64 ports at one address, in 4096-datagram bursts. Noise used a captured
transport prefix with altered ciphertext. Useful UDP requested 6000
application datagrams/s with 128-byte payloads for 60 seconds, using
`iperf3 -u -b 6144000 -l 128 --pacing-timer 1000 -t 60 -O 0 -J`, with
`-R` for download. Actual source duration and counts are retained; the
reverse server can keep sending while the control exchange finishes.
Application datagrams and captured GSO/GRO frames are counted separately.

Netem added 150 ms in each A-B direction, including the mutual-TLS control
channel. Jitter trials added normal variation of 30 ms per direction.
Both queues held at most 16,384 packets, with no configured loss. Twenty
physical pings checked RTT before each trial. Management and the noise-to-A
path had no added delay. Seeds and samples are in the data.

Each native profile sent 100 ordinary probes at nominal 500-ms intervals.
Profile 1 also sent 100 probes at 50-ms intervals, starting at second 23.
Both probes used a one-second deadline. Their ICMP identifiers were
checked against inner captures. UDP sequence analysis handles combined
GSO/GRO payloads and a short startup-control tail.

Acceptance requires qualified noise, useful sender rate within 1% and
receiver rate within 5% of 6000/s, complete delivery of unique UDP sequences,
all 200 ordinary and 100 frequent replies by the deadline, and zero
client/control guard, NFQUEUE/netlink, emulator or capture drops. Noise
must obtain no lease. CPU includes all stored nominal 250-ms samples and
rolling four-sample windows, including noise startup, but has no pass/fail
threshold. Of 24 counted trials, 13 pass this criterion; all six final
trials pass. Three excluded attempts are described below.

## Recovery design

The C classifier, nftables rules and Python admission agent are unchanged
from v21. B's optional receiver/sender patch copies already encrypted
outbound transport packets into a ring. It does not cache handshakes or
keepalives. The ring holds at most 8192 packets and 8 MiB of ciphertext,
plus fixed metadata. The final build selects packets younger than 500 ms;
an idle cleanup runs every 100 ms. Packet ownership uses a SHA-256 peer
public-key hash and scalar keypair creation-time/local-index fields.
There is no extra plaintext, session key or keypair pointer in the ring.

A changed endpoint must come from fresh authenticated transport that passes
replay and source-policy checks. B commits this endpoint before selecting
the recovery snapshot. The sender records each encrypted packet before
reading its endpoint. This ordering lets later packets use the new path
while older eligible packets are copied from the snapshot.

A recovery attempt sends at most 4096 packets and 2 MiB in original send
order. A peer waits at least one second between cache lookups, including
empty ones. Nonempty attempts are at least 250 ms apart globally. A single
in-flight guard skips concurrent recovery instead of queuing more copies.
Sending is synchronous; it can delay that peer's receiver while the burst
is sent. Normal endpoint updates still proceed when a recovery limit
prevents copying. Clients retain their own replay checks, so already
received ciphertext does not produce another plaintext delivery.

The option requires `COLDWIRE_LAB_RETURN_REPLAY=1` and the existing proof
socket setup. It is off by default. Build and lab-only setup are in the
[helper README](flow-confirmation/README.md); ordinary VPS installers do
not deploy this patch.

## Final 500-ms build

The final binary is B4, SHA-256
`19b0b187bff038172d5817abbc11fb244b6f7a3336e94679e736c4b83715ed01`.
Jitter is per direction; RTT target is 300 ms in every row. Max RTT covers
all frequent replies, including late ones in the control table. CPU is
the maximum whole-VM sample across all four guests and is informational.

| Direction | Jitter ms | Move | UDP sent | UDP missing | Frequent / 100 | Ordinary / 200 | Max RTT ms | Peak CPU % |
|---|---|---|---|---|---|---|---|---|
| B to client | 30 | IP + port | 362028 | 0 | 100 | 200 | 649.28 | 70.00 |
| B to client | 30 | IP | 362489 | 0 | 100 | 200 | 648.20 | 69.23 |
| Client to B | 0 | IP + port | 360001 | 0 | 100 | 200 | 634.28 | 65.00 |
| Client to B | 0 | IP | 360001 | 0 | 100 | 200 | 626.09 | 70.00 |
| Client to B | 30 | IP + port | 360001 | 0 | 100 | 200 | 583.10 | 82.14 |
| Client to B | 30 | IP | 360002 | 0 | 100 | 200 | 626.69 | 95.83 |

The final maximum frequent-probe RTT was 649.28 ms. Peak CPU by role was
A 56%, B 70%, C 95.83% and D 26.92%. B's AWG process reached an RSS high-water
mark of 84.38 MiB with the stock `GOMEMLIMIT=96MiB`; no guest logged an OOM
kill. RSS measures resident memory; the larger recorded `VmPeak` measures
virtual address space. These values describe this host and workload. Other VPS hardware was
not measured.

## Controls and development findings

Build IDs refer to the binary hashes in the data. B0 is the initial
recovery-disabled control. B1 adds the single in-flight guard; B2 also
consumes the peer cooldown when the cache is empty. Both retain a 750-ms
window and the old endpoint/snapshot order. B3 commits the endpoint first,
still with 750 ms. B4 shortens eligibility to 500 ms. Earlier source
snapshots and logs remain local; the current source builds B4.

| Build / mode | Direction | Jitter ms | Move / repeat | UDP missing | Frequent / 100 | Ordinary / 200 | Max RTT ms | Peak CPU % |
|---|---|---|---|---|---|---|---|---|
| B2/off | B to client | 30 | IP + port / 3 | 1817 | 94 | 200 | 410.44 | 62.96 |
| B2/off | B to client | 30 | IP / 3 | 1910 | 93 | 200 | 406.64 | 63.33 |
| B1/off | Client to B | 0 | IP + port / 0 | 0 | 93 | 199 | 341.37 | 85.71 |
| B1/off | Client to B | 0 | IP / 0 | 0 | 93 | 199 | 346.42 | 85.71 |
| B0/off | Client to B | 30 | IP + port / 0 | 0 | 95 | 199 | 430.50 | 81.48 |
| B1/off | Client to B | 30 | IP + port / 1 | 0 | 96 | 200 | 421.34 | 85.71 |
| B0/off | Client to B | 30 | IP / 0 | 0 | 96 | 199 | 435.56 | 91.30 |
| B1/off | Client to B | 30 | IP / 1 | 0 | 95 | 200 | 472.94 | 83.33 |
| B2/on | B to client | 30 | IP + port / 3 | 1 | 100 | 200 | 811.29 | 80.00 |
| B3/on | B to client | 30 | IP + port / 4 | 0 | 100 | 200 | 711.96 | 60.00 |
| B2/on | B to client | 30 | IP / 3 | 1 | 100 | 200 | 682.29 | 73.33 |
| B3/on | B to client | 30 | IP / 4 | 0 | 99 | 200 | 1017.88 | 64.29 |
| B1/on | Client to B | 0 | IP + port / 0 | 0 | 100 | 200 | 623.22 | 86.96 |
| B1/on | Client to B | 0 | IP / 0 | 0 | 100 | 200 | 656.52 | 85.71 |
| B1/on | Client to B | 30 | IP + port / 0 | 0 | 100 | 200 | 532.80 | 80.95 |
| B3/on | Client to B | 30 | IP + port / 1 | 0 | 100 | 200 | 576.82 | 72.73 |
| B1/on | Client to B | 30 | IP / 0 | 0 | 100 | 200 | 520.57 | 84.00 |
| B3/on | Client to B | 30 | IP / 1 | 0 | 100 | 200 | 541.39 | 75.00 |

B2 lost one reverse UDP datagram in each movement trial. In the IP-only
trial, the missing packet was generated 1.813 ms after the first new-path
frame reached B's IFB tap. The code allowed a packet to be created after
the recovery snapshot but still read the old endpoint. A deterministic
test injects a send at that point: the old order fails, the endpoint-first
order passes. The historical endpoint write itself was not traced, so
its exact timing remains an inference from the capture and code.

B3's two reverse trials delivered every UDP sequence. One frequent reply
arrived after its deadline: 1017.674 ms between client TUN captures and
1017.883 ms at the probe, with only 0.177 ms between capture and userspace
read. This was a real path delay. The 500-ms candidate keeps less history
and can resend fewer old copies at this offered rate. Its final trials
had no late replies. Seeds and scheduling differ between repetitions;
this does not isolate a statistical latency effect of the window change.
A shorter window also reduces coverage when discovery of the new path
is delayed.

All 24 counted trials have complete noise-rate observations, totaling
42,000,000 offered noise datagrams. Client/control guard, NFQUEUE/netlink,
netem and capture drops are zero throughout; noise received no lease.
The data retains all controls, raw iperf estimates and both probe results.

## Measurement corrections

One reverse attempt with full, packet-flushed outer captures dropped
207,037 capture frames on A, 23,779 on B and 24,017 on C. It is excluded
from the counted matrix. Reverse trials now use buffered inner UDP
captures at both ends; upload retains the low-rate outer reply captures.
All captures in counted trials have zero kernel drops.

A second reverse attempt failed before its first iperf interval. Its valid
UDP startup ACK arrived after 126 data datagrams, as the four-byte tail of
a 132-byte GRO frame. For this block size, the
[3.18 connect loop](https://github.com/esnet/iperf/blob/3.18/src/iperf_udp.c#L549)
and [reorder constant](https://github.com/esnet/iperf/blob/3.18/src/iperf.h#L442)
allow 65 four-byte reads. A separate iperf3 3.18 benchmark build raises
`MAX_REVERSE_OUT_OF_ORDER_PACKETS` from 2 to 256, allowing 8193 reads.
Its archive/binary hashes and build settings are in the data. It changes
startup tolerance, while retaining the requested pacing and payload.
Original iperf and native VPN binaries were kept. All counted reverse
trials use this same benchmark build for recovery off and on.

The sequence parser now counts full datagrams preceding a four-byte
control tail; a self-test covers that case. A third attempt saved its raw
row before an old harness assertion rejected the intentional reverse
direction. Its postprocessing was incomplete, so it is excluded too.
The assertion now uses the actual UDP direction.

Iperf's positive loss estimates remain in the data. For example, the final
reverse IP-only run reported 929 lost while both tunnel captures contain
all 362,489 unique datagrams. Startup/end accounting can omit packets that
reached the tunnel. Captures establish VPN delivery; they do not establish
that the application consumed or credited every datagram. Probe deadlines
are unchanged and late replies remain separate from timely ones.

## Checks, rollback and limits

The final source passed 20 top-level Go device tests and one replay-package
test. Two upstream tests remain skipped: the manual handshake test and the
disabled wait-pool test. Coverage includes cache ownership/epoch isolation,
expiry, packet/byte bounds, cooldowns, single in-flight behavior, a real
encrypted-packet drop followed by recovery, and suppression of duplicate
plaintext. The endpoint-order negative control fails as expected. Seven
Python agent tests pass on Windows and both Linux server guests. The
patcher rejects a second application without changing source files.

Live lab controls confirm lease expiry while A's helper is stopped,
rejection of 200 full-ciphertext replays without a fresh proof or noise
lease, and mutual-TLS rejection without a client certificate. Spoofing a
leased tuple still passes A; B rejects altered ciphertext and the lease
does not refresh. Recovery copies ciphertext without changing its counter
or re-encrypting plaintext. No replay-send error was logged.

Before shutdown, stock B binary/unit/environment, ordinary DNAT, client
NAT and both original profiles were restored. Both native probes passed.
Owned delay/IFB, rules, helpers and capture jobs were removed or stopped;
original entry settings were restored. All four guests, seed server and
switch are stopped, with eleven loopback ports free. Parent disks, prior
v1-v21 reports/data and personal JSON hashes match. Production servers,
the user's VPN, Windows networking and GitHub were not changed.

Recovery remains best effort. Larger delays, a late first client packet,
key changes, cache eviction, rapid/concurrent moves or a client replay-window
limit can defeat it. A registered peer can trigger bounded retransmission
without proving return reachability. Repeated ciphertext adds a linkable
wire pattern; DPI and unlinkability were not tested. Physical GUI clients,
distributed noise and candidate-table exhaustion were not tested either.
Keep the option off on active servers while these limits are evaluated.
