# Virtio notifications and egress loss

English | [Русский](validation-v14.ru.md)

Test date: 13 November 2026. Keep the current filter and default Virtio
settings. Larger rings, a larger NAPI budget and legacy-only Virtio did not
give a repeatable advantage. New counters localized some loss after entry
routing; a FIFO control removed that loss but did not resolve the service
failures in those comparisons.

The final return to the original configuration passed six short trials at
25,000 noise packets/s and about 100 Mbit/s TCP, including the two recognizable
junk payloads. It returned 1200/1200 echo replies; peak whole-VM CPU was 60%.
This followed fixes to lab service lifecycle checks and host-load controls.
Earlier failed and aborted acquisitions remain in [the results](results-v14.json).

## Setup and checks

Four disposable Debian 13 guests each had one vCPU and 1024 MiB RAM. Entry,
exit and client used kernel 6.12.116; the noise guest used 6.12.115. The Windows
host had a Ryzen 9 5950X with 32 logical CPUs. QEMU 11.1.3 used WHPX and the
same patched socket backend as [v11](validation-v11.md). CPU affinity, quotas,
Windows networking and WSL were unchanged.

The filter kept its 4096-packet queue, 212-byte copy limit and grouped individual
verdicts. The kernel guard kept 35,000/s with burst 3500 per tuple and 50,000/s
with burst 5000 in aggregate. AWG binaries, keys and client profile files were
unchanged. Accepted traffic still required authentication at B.

Each trial offered 300,000 fixed 256-byte UDP payloads over twelve seconds,
one source tuple, with offered bursts up to 4096. The two native Linux AWG
clients requested 50 Mbit/s each, one upload and one download. Each also sent
100 fixed ICMP requests, 20 ms apart, with a one-second reply budget. The
captured-prefix fixture recreated client 1's session and took a fresh capture
before each trial. This setup did not retest GUI clients or external-IP changes.

Sender, native switch and entry counters independently checked the noise
rate. The 66 completed trials all met the rate gate: sender and native arrival
means within 1% of 25,000/s, entry delivery within 1%, no switch drops and a
complete switch count. They offered 19,800,000 datagrams. Four further workload
attempts aborted and are recorded separately; one has no completed sender total.

A service pass required each TCP stream within 5% of 50 Mbit/s, all 200 echo
replies, agreement with inner captures, no NFQUEUE/netlink/client-guard or
client-shaper drops, and every whole-VM CPU sample and sliding four-sample
window at or below 90%. Samples were nominally 250 ms and included observer
cost. This is not an instantaneous CPU ceiling. Noise admission and egress
discards are separate measurements. The six instrumented QEMU runs are
diagnostics, even where their service metrics passed.

## Where output packets disappeared

New nftables counters selected only the noise tuple: A after the prefilter,
A after routing/SNAT just before the egress qdisc, and B at raw ingress.
For fixed IPv4/UDP payloads, `(bytes - 28 * skb_packets) / 256` normalizes
possible packet grouping. The JSON retains byte and skb counts.

Snapshots settled to three identical counter readings with an empty output
queue. A persistent NETLINK_ROUTE reader also sampled root-qdisc backlog,
queue length, drops and requeues during CPU collection. It avoided running
`tc` inside those windows. Parser self-checks and comparison with `tc` passed.

In the first random-DNAT trial, all 300,000 datagrams passed A's routed
counter, B counted 299,999 and A's root `fq_codel` counted one drop. In the
first captured-prefix trial, A routed 286,976, B counted 286,929 and root
`fq_codel` counted 49 drops. The 47-packet noise deficit cannot account for
every aggregate qdisc drop, since the qdisc also handled legitimate traffic.

Across six FIFO controls, root drops and the routed-noise deficit at B were
both zero. These controls support egress queue management as a cause of this
newly observed loss. Small `fq_codel` losses generally had `drop_overlimit=0`;
the enlarged-NAPI experiments also produced hard-limit overflow. FIFO still
failed the full service criteria in all six comparisons. It was restored to
`fq_codel` and is not a recommended production workaround.

The twelve missing noise packets in [v13](validation-v13.md) were not traced
retrospectively. The new counters localize loss in the present experiment.

## Virtio controls

The initial PCI ID was transitional, but negotiated feature bit 32
(`VIRTIO_F_VERSION_1`) already selected the modern transport. Bit 29
(`EVENT_IDX`) was also negotiated. Only A's data NIC changed; its management
NIC and the other guests kept their settings.

Each row below combines two trials for each of random-DNAT, filtered valid
MAC1/invalid Noise, and filtered captured prefix. The second repeat reversed
their order. These sequential comparisons have substantial runtime variation;
their throughput ranges do not establish a causal speed ranking.

| Configuration | Service passes | Total Mbit/s range | NFQUEUE drops | Routed noise missing at B |
|---|---:|---:|---:|---:|
| Original RX/TX 256, NAPI 64 | 0/6 | 37.38–65.47 | 67301 | 211 |
| RX 1024 | 1/6 | 36.40–106.41 | 11222 | 100 |
| Return to RX 256 | 0/6 | 33.37–106.42 | 37116 | 178 |
| FIFO instead of fq_codel | 0/6 | 30.16–107.59 | 33138 | 0 |
| RX/TX NAPI 256 | 1/6 | 30.47–99.85 | 41109 | 10490 |
| RX NAPI 256, TX NAPI 64 | 0/6 | 32.78–45.73 | 20064 | 20315 |
| Legacy-only, RX/TX 256 | 3/6 | 52.42–100.16 | 12411 | 59 |
| Legacy-only, RX 1024 | 0/6 | 40.42–97.12 | 23020 | 170 |

RX 1024 and NAPI 256 reduced notification counts without giving a reliable
service pass. In Linux 6.12, the refill threshold is `min(budget, ring_size)/2`,
so ring size alone does not determine notification frequency. A larger NAPI
budget also changes how much RX/TX work happens per poll. The NAPI 256
runs recorded fewer kicks along with substantial queueing and requeues. A separate
RX-256/TX-64 NAPI control did not fix it. These numbers refer to poll budgets,
not ring sizes. See the [Linux driver](https://github.com/torvalds/linux/blob/v6.12/drivers/net/virtio_net.c).

The non-vhost QEMU socket backend allowed a TX ring of at most 256. Requesting
1024 failed before load and was not counted as a workload trial. The backend
limit was not patched. Legacy-only Virtio passed all three first-repeat cases,
then failed their second repeats. Increasing its RX ring did not resolve this.

## What WHPX timing measured

A private diagnostic build timed `WHvRunVirtualProcessor`, MMIO, PIO and the
pre/post handlers in `whpx-all.c`. It emitted cumulative counters once per
second. Differences used records strictly inside each host-QPC measurement
window. The executable was used only for six diagnostic runs. Shared source
and the ordinary executable were restored; an uninstrumented rebuild had an
identical `.text` section to the original baseline.

| Transport | Payload/policy | MMIO + PIO handler wall time, % |
|---|---|---:|
| Modern | Random/DNAT | 18.94 |
| Modern | Valid MAC1/filtered | 2.81 |
| Modern | Captured prefix/filtered | 4.14 |
| Legacy | Random/DNAT | 50.78 |
| Legacy | Valid MAC1/filtered | 9.01 |
| Legacy | Captured prefix/filtered | 14.10 |

These are wall times in all entry MMIO/PIO handlers, including synchronous
callbacks and waiting. They do not isolate the NIC register write or express
a fraction of guest CPU. The legacy-prefix diagnostic also encountered 100%
host load. These acquisitions differ from v13's guest `perf` recording;
its 38.16% `iowrite16` sample share cannot be substituted for these times.
The measurements do not justify changing to legacy transport.

## Lab failures and fixes

Two return attempts ended with iperf 3.18 reporting a closed control socket;
the server logged an idle receive timeout. An isolated loopback control on B
reproduced the mechanism without AWG or noise. Delaying only data payloads
by 2.5 seconds gave:

| Server idle before connect | Receive timeout | Native client status | Elapsed, seconds |
|---:|---:|---:|---:|
| 0 s | 4 s | 0 | 5.014 |
| 6 s | 4 s | 1 | 1.014 |
| 6 s | 120 s | 0 | 5.013 |

Small control packets bypassed the delay. A preceding negative control that
delayed only the data SYN passed all three cases. The
[3.18 server source](https://github.com/esnet/iperf/blob/3.18/src/iperf_server_api.c)
initializes receive timing before accepting the connection. This supports the
timer explanation for the return failures, although their exact TCP packet
history was not captured. The corrected series restarts both listeners before
each trial and keeps nonzero native output before raising an acquisition error.

Four subsequent completed trials encountered 100% Windows-host load and failed
service criteria. In their DNAT case, the helper credited no replies within
its one-second budget, although inner captures saw later replies; each helper
also read 51 late replies. This is why global capture agreement is false in
the JSON. The other 65 completed cases agree. Those four runs remain visible
and cannot establish a Virtio configuration comparison.

After two successful low-host-load controls, the next attempt exceeded its
40-second TCP deadline. Journal timestamps showed client 2's disposable AWG
service reaching `RuntimeMaxSec=7200` during that attempt; later probing
reported `Network is unreachable`. Both clients were recreated using the
original profile files. The final series checks that both services are active
with more than 60 seconds remaining before launching a bounded trial. This
changes the lab lifecycle, not the installed VPN service on a VPS.

The Windows snapshot reader also hit a transient sharing denial while reading
the switch's replaced statistics file. It now retries that error within the
existing two-second bound and still rejects stale snapshots. Retry and bounded
failure self-checks passed. This setup failure occurred before noise launch.

One other workload acquisition stopped before the controller completed its
case record. Its raw guest output and inner captures were retained; it has no
complete CPU/rate pair and no completed sender total. It is recorded in the
JSON ledger alongside the two iperf failures and the expired
client service. None is counted as a successful or completed trial.

## Final return to the original configuration

Entry returned to the original executable, modern transport, RX/TX 256,
NAPI 64 and `fq_codel`. Both native clients had fresh service lifetimes; iperf
listeners restarted per trial. Every two-second host preflight stayed below
25% busy; peak host load during the six measured windows was 26.36%.

| Payload/policy | Total Mbit/s range | Peak CPU, any VM % | Echo replies | Passes |
|---|---:|---:|---:|---:|
| Random bytes, ordinary DNAT | 99.90–100.00 | 60.00 | 400/400 | 2/2 |
| Valid MAC1, invalid Noise, filtered | 99.77–99.90 | 52.00 | 400/400 | 2/2 |
| Captured transport prefix, filtered | 100.09–100.19 | 52.00 | 400/400 | 2/2 |

Native arrival means were 25,050.29–25,051.76 packets/s. All six counted
300,000 at sender, switch, entry, A's routed counter and B. NFQUEUE, netlink,
guard, experimental ingress-shaper and egress drop counters stayed zero;
inner captures agreed with all reported echo sequences. Each TCP stream met
its target independently.

This establishes six successful short return controls after the lab fixes.
Several controls changed together, so it does not assign every earlier
throughput difference to a timer or to host load. It does not establish
sustained capacity under an arbitrary host workload or adaptive attacker.

## Decision and cleanup

Keep queue 4096 and the normal NIC/qdisc defaults. Keep host-load and service
lifetime checks in the lab, and record failed native workloads separately.
Further work should start with longer repeats under controlled host load,
before changing the filter to address a presumed Virtio bottleneck.

Both native profiles passed after rollback; their files, filter binaries and
personal JSON hashes were unchanged. Temporary observation tables and capture
units were removed. All four VMs, seed server and switch were stopped; all
eleven lab ports were free. Live servers, the user's VPN and Windows networking
were untouched. GitHub was not updated during this stage.
