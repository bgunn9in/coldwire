# Recognizable junk and the filter's load limit

English | [Русский](validation-v13.ru.md)

Test date: 13 November 2026. Keep the 4096-packet queue. Doubling it removed
NFQUEUE overflow in four comparisons, but none met the throughput and 90%
whole-VM CPU criteria. The largest measured echo RTT was 408 ms.

The unchanged filter passed twelve final trials at 15,000 recognizable junk
packets/s plus about 100 Mbit/s TCP: 2400/2400 echo replies, peak guest CPU
80.77%. Recognizable junk at 25,000/s did not pass reliably. Random bytes and
invalid MAC1 remained cheaper to reject. These are short lab observations,
not a production capacity guarantee.

## Setup and acceptance

Four fresh disposable Debian 13 overlays each had one vCPU and 1024 MiB RAM.
The AWG client/server, ordinary prototype binaries, native Windows switch
and patched QEMU were the same as [v12](validation-v12.md). The filter copied
212 bytes and used grouped individual verdicts. The lab kernel guard kept
its 35,000/s per-tuple bucket with burst 3500 and aggregate 50,000/s with
burst 5000. No CPU quota was applied.

Two Linux native AWG clients each requested 50 Mbit/s. Primary comparisons
used one upload and one download. The final series covered both upload,
both download and mixed, twice for each difficult payload, reversing order.
The [bounded probe](lab-switch/icmp-probe.py) sent 100 requests per client,
20 ms apart, with a one-second reply budget. Client and exit ICMP captures
checked the reported sequences.

Each noise workload lasted twelve seconds, used a fixed 256-byte payload
and one UDP source tuple, with offered bursts up to 4096. Rates describe
twelve-second means, not constant instantaneous pacing. Trials qualified
only if sender rate was within 1%, delivery to entry was within 1% and the
switch dropped nothing. Every analyzed trial met that gate; sender, switch
and entry counted all 13,860,000 offered packets independently.

A pass also required each TCP stream within 5% of 50 Mbit/s, all 200 echo
replies agreeing with captures, no NFQUEUE/netlink/client-guard or experimental
ingress-shaper drops, and every whole-guest CPU sample/window at or below
90%. CPU came from nominal 250-ms samples and sliding four-sample tick
windows, including observer cost. This does not establish an instantaneous
ceiling or require every junk packet to reach B. Egress AQM drops are
reported separately. Echo p99 uses the nearest-rank percentile, recomputed
from the retained raw helper replies.

B's raw-priority counter selected the translated noise source/port. With
fixed-size IPv4/UDP payloads, `(bytes - 28 * skb_packets) / 256` normalizes
possible GRO grouping. The JSON retains both original counter fields;
this count is independent of the inner ICMP captures.

## Payload controls

All four fixtures were checked through the actual prefilter's offline mode
before load tests. Correct Header Protection with altered initiation content
failed MAC1; a valid MAC1 initiation with a zero sender/ephemeral/body passed
as initiation despite invalid Noise. Handshake fixtures were padded to
256 bytes; the disposable exit had `RandomTrailers=on`.

The captured-prefix fixture kept the first 28 bytes of a real transport
packet, then replaced the remaining 228 bytes. The sender had no key file.
The first matrix reused one capture and did not control its age. Queue and
rate sweeps captured again before each trial. Profiling and final repeats
also recreated client 1's session before capture, using the same profile
and keys. Session creation occurred before load; forced rehandshakes and
roaming during these recognizable floods were not controlled. These controls establish admission of altered packets; they do
not benchmark every possible receiver-index or AEAD state.

B still authenticates VPN traffic. Passing A's header/MAC1 check establishes
neither a valid peer nor decryptable data. The pinned
[AWG receive path](https://github.com/amnezia-vpn/amneziawg-go/blob/1b86b2ae0e493e7ea93f8c1a0f0cb6735b1551f1/device/receive.go)
keeps key-pair lookup and transport authentication at B. The fixed invalid
Noise fixture does not bound more expensive, adaptive constructions.

## Initial comparison at 25,000/s

The filtered policy combined the unchanged kernel guard and queue-4096
binary. Two trials per payload gave:

| Payload | Mbit/s median | Entry peak CPU % | Echo replies | NFQUEUE drops | Noise received by B | Passes |
|---|---:|---:|---:|---:|---:|---:|
| Random bytes | 99.98 | 53.57 | 400/400 | 0 | 0/600000 | 2/2 |
| Invalid MAC1 | 99.98 | 64.00 | 400/400 | 0 | 0/600000 | 2/2 |
| Correct MAC1, invalid Noise | 38.96 | 100.00 | 387/400 | 18985 | 582215/600000 | 0/2 |
| Captured transport prefix | 62.27 | 90.48 | 394/400 | 16168 | 585049/600000 | 0/2 |

All sixteen DNAT/kernel-guard reference trials reached 100% entry CPU and
failed the 90% criterion. Their total TCP ranged from
75.90 to 90.70 Mbit/s. The guard's unchanged rates admitted
almost all noise in those controls; it was not configured to cap a 25,000/s
single-source workload.

Recognizable traffic passed the partial check and then encountered queue
or guard drops. Unlike the timeout controls in v12, the missing echo replies
were also absent from client captures. Queue counters cover all selected
traffic, so their totals must not be assigned entirely to noise or to ICMP.

## Queue-8192 comparison

Only `QUEUE_MAXLEN` changed in a private candidate. `make check check-batch`
passed; ready telemetry and both experimental tables were verified before
testing. The original prototype source and binaries remained intact.
Two comparisons per payload, with order reversed, gave:

| Payload | Queue | Mbit/s median | NFQUEUE drops | Noise guard drops | Worst echo p99 ms | Passes |
|---|---:|---:|---:|---:|---:|---:|
| Correct MAC1, invalid Noise | 4096 | 76.72 | 9587 | 126 | 254.74 | 0/2 |
| Correct MAC1, invalid Noise | 8192 | 53.42 | 0 | 7329 | 295.76 | 0/2 |
| Captured transport prefix | 4096 | 70.60 | 8977 | 73 | 226.32 | 1/2 |
| Captured transport prefix | 8192 | 40.84 | 0 | 16160 | 389.70 | 0/2 |

The four larger-queue runs returned all echo replies and reported no
NFQUEUE overflow. They still failed useful throughput/CPU, and guard drops
remained. The candidate was not adopted. A larger queue alone does not
resolve this burst workload.

## Lower-rate repeats

Single mixed-direction screens passed at 5000, 10,000 and 15,000/s for both
recognizable payloads. Both 20,000/s screens failed the full criteria.
At 15,000/s, the original binary then passed all twelve final trials:

| Payload | Runs | Mbit/s range | Peak CPU, all VMs % | Echo replies | Passes |
|---|---:|---:|---:|---:|---:|
| Correct MAC1, invalid Noise | 6 | 99.63 to 100.73 | 80.77 | 1200/1200 | 6/6 |
| Captured transport prefix | 6 | 99.69 to 100.53 | 80.77 | 1200/1200 | 6/6 |

Sender means were 14999.823 to 14999.891/s. Peak CPU by guest was A 80.00%, B 80.77%,
C 80.77% and D 28.00%. Filter RSS at the final snapshots was
6488 to 6560 KiB; this excludes kernel queues and the AWG service.
All final echo sequences matched at application and tunnel captures.
NFQUEUE, netlink, guard, experimental ingress shaper and switch drop
counters stayed zero in these repeats.

The exit's byte-normalized counter saw 2,159,988 of 2,160,000 noise datagrams
in the final series. Entry egress `fq_codel` also counted
28 drops across the trace windows. Those windows include quiescent snapshots;
the remaining 12-packet noise deficit was not localized packet by packet.
This is not a zero-loss claim for the whole relay. It does not invalidate
the observed 2400 echo replies or authorize attributing aggregate discards
to specific packets.

## Profiling and interpretation

Three separate diagnostics sampled entry with `perf record`, software
`cpu-clock`, 99 Hz for 18 seconds. All exited successfully and reported
zero lost samples. They are not qualification repeats because sampling
can change timing.

In the DNAT recording, `iowrite16` under `ksoftirqd/0` accounted for 38.16%
of self samples, with a call path through `vp_notify`, `virtqueue_notify`,
`try_fill_recv` and `virtnet_poll`. Percentages cover the entire recording,
including idle/setup, not just busy CPU. In the filtered diagnostics,
virtqueue notifications also appeared. This points to substantial virtual
NIC cost; it does not prove an equivalent cost on a real VPS or explain
every overflow. Earlier DNAT passes remain valid observations of their
own runs, not a universal guarantee for this backend.

The [results JSON](results-v13.json) retains 55 completed trials: 24 primary,
eight queue comparisons, eight rate screens, three profiling diagnostics
and twelve final repeats. Applications and client captures agreed on
10,938/11,000 echo replies across the entire study. All analyzed ICMP
captures reported zero kernel capture drops. Failed measurements remain
in the data.

## Decision and rollback

Keep the 4096 default and the prototype's experimental status. Its measured
benefit covers blind noise and invalid MAC1. The tested recognizable
25,000/s bursts remain outside the demonstrated service budget; 15,000/s
is a qualified lab point, not a hard capacity limit or a protective rate
preset. A shared rate budget can also harm fresh clients, so this study
does not introduce one as an authentication substitute.

The next useful measurement is to separate egress AQM loss and virtqueue
notification cost from NFQUEUE processing on the accepted-packet path.
Changing queue size again or benchmarking only rejected random packets
would leave that question open.

Rollback restored ordinary DNAT and original client NAT/runtime settings.
Both original profiles passed probes; profile, original filter and personal
JSON hashes were unchanged. Temporary counters and captures were removed,
all four VMs and host helpers stopped, and eleven lab ports released.
Live servers, the user's VPN, WSL and Windows networking were untouched.
Physical GUI clients, real VPS and DPI evasion were not tested. English
and Russian prose was reviewed with Humanizer.
