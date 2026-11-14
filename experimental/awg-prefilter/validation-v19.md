# Packet loss while the client address changes

English | [Русский](validation-v19.ru.md)

Test date: 14 November 2026. Separating transport credit from unknown control traffic removed
the measured early client losses during the tested IP and NAT-port changes.
The final policy passed 12 mobility trials with zero client-guard,
NFQUEUE and reported useful-UDP losses. Both native profiles, their code and
listen ports were unchanged. All changes of address occurred on the lab gateway.
[Rules and setup](flow-confirmation/README.md), [data](results-v19.json).

## Cause and change

In [v18](validation-v18.md), the moving tuple lost 293 and 589 packets before
its fresh proof from B. The old tuple and the other client lost none. The
aggregate and NFQUEUE drop counters were zero, locating those early losses
in the per-source guard. This series reproduced 644 and 472 early losses
with the original 64-packet source burst. CPU was below 53% in those controls.

A new IP has no authenticated lease yet. The old guard immediately limited
it to 1500 packets/s with only 64 packets of initial credit, while an active
client could already be sending several thousand packets/s. No client-IP
allowlist can reliably solve that for a roaming address.

The transport change is two nftables values: source burst 64 → 4096 and aggregate
burst 256 → 1024. Sustained ceilings stay at 1500/s per unknown source and
6000/s in aggregate. These are token-bucket capacities, replenished at the
same rates; no packet buffer or new process was added. All unknown packets
still take the existing Header Protection/MAC1 path. A still requires a new
post-query authenticated event from B before installing its ten-second
conntrack-bound lease. The Python agents, Go hook and proof protocol are unchanged. An optional
C build adds classification marks after the same cryptographic inspection.
A post-queue gate limits unleased initiation/response/cookie messages to
20/s with burst 8 per source and 100/s with burst 16 overall. Data keeps
the larger credits. These are local netfilter marks; payload is not replaced.
The classification-ready mark is required, so an older unmarked binary
fails closed with the new combined rules.

## Trials and acceptance

Four new COW guests over the stopped v18 lab disks ran Debian 13 kernel
6.12.116 under QEMU 11.1.3/WHPX, each with one vCPU and 1024 MiB RAM.
The two unmodified native AWG profiles shared one guest. Virtio RX/TX 256,
NAPI 64, fq_codel, queue 4096, copy range 212 and grouped verdicts were retained.
No quota, affinity, host network, power or WSL changes were made.

Each trial offered 25,000 fixed-size noise datagrams/s for 70 seconds in
4096-packet bursts. Noise used 64 source ports; the additional MAC1 tests
also used eight ports. All noise came from one lab IP. Fixtures were a fresh
transport header/prefix with altered ciphertext and a valid MAC1 with an
invalid Noise body. A never granted the noise source a lease.

TCP requested 50 Mbit/s in each of two mixed-direction streams. UDP requested
6000 application packets/s with 128-byte payloads and a 1000-us pacing timer.
Bulk traffic lasted 60 seconds after one omitted second. Each profile sent
100 probes at 500-ms intervals with a one-second deadline. The gateway changed
only client 1's public IP, or both public IP and NAT source port, 25 seconds
after bulk traffic began. Native ports stayed 32497/32498 and profile hashes
matched before and after every trial. Original and translated ports were
checked separately; IP-only movement forces A's SNAT port remap.

Acceptance requires complete sender/switch/entry counts and native arrival
timing within 1% of the requested rate, TCP within 5% of target, UDP sender
within 1%, receiver within 5% and zero reported UDP loss. It also requires
200/200 probes matching inner captures, no early-client/NFQUEUE/netlink/shaper
loss, and CPU at most 90% on every guest. CPU now covers every stored resident
sample, including the first noise burst, plus all four-sample windows. The
older main-window numbers are retained separately. Samples are nominally
250 ms; no process census, queue polling or fprobe runs during load.

## Calibration attempts

| Burst source / all | Move | Noise | Useful traffic | Client discards | NFQUEUE | Echoes | CPU % | Pass |
|---|---|---|---|---:|---:|---:|---:|---|
| 2048 / 1024 | IP+NAT port | 64 prefix | 49.99 / 50.00 Mbit/s | 0 | 0 | 200/200 | 43.48 | yes |
| 2048 / 1024 | IP+NAT port | 64 prefix | 6000 UDP PPS | 137 | 0 | 200/200 | 83.33 | no |
| 2048 / 1024 | IP | 64 prefix | 50.05 / 50.03 Mbit/s | 0 | 0 | 200/200 | 56.00 | no |
| 2048 / 1024 | IP | 64 prefix | 6000 UDP PPS | 321 | 0 | 200/200 | 80.00 | no |
| 2048 / 256 | IP+NAT port | 64 prefix | 50.00 / 50.00 Mbit/s | 130 | 0 | 200/200 | 33.33 | no |
| 2048 / 256 | IP | 64 prefix | 49.99 / 50.00 Mbit/s | 371 | 0 | 200/200 | 41.67 | no |
| 4096 / 1024 | IP+NAT port | 64 prefix | 49.99 / 50.00 Mbit/s | 0 | 0 | 200/200 | 39.13 | yes |
| 4096 / 1024 | IP+NAT port | 64 prefix | 50.00 / 50.00 Mbit/s | 0 | 0 | 200/200 | 52.00 | yes |
| 4096 / 1024 | IP+NAT port | 64 prefix | 50.00 / 50.00 Mbit/s | 0 | 0 | 200/200 | 46.15 | no |
| 4096 / 1024 | IP+NAT port | 64 prefix | 50.00 / 50.00 Mbit/s | 0 | 0 | 200/200 | 46.15 | yes |
| 4096 / 1024 | IP+NAT port | 64 prefix | 6000 UDP PPS | 0 | 0 | 200/200 | 85.71 | yes |
| 4096 / 1024 | IP+NAT port | 64 prefix | 6000 UDP PPS | 0 | 0 | 200/200 | 80.77 | yes |
| 4096 / 1024 | IP+NAT port | 64 MAC1 | 50.00 / 50.00 Mbit/s | 0 | 0 | 200/200 | 37.50 | yes |
| 4096 / 1024 | IP | 64 prefix | 49.99 / 50.00 Mbit/s | 0 | 0 | 200/200 | 40.91 | yes |
| 4096 / 1024 | IP | 64 prefix | 49.99 / 50.00 Mbit/s | 0 | 0 | 200/200 | 40.00 | yes |
| 4096 / 1024 | IP | 64 prefix | 50.05 / 50.03 Mbit/s | 0 | 0 | 200/200 | 44.00 | yes |
| 4096 / 1024 | IP | 64 prefix | 6000 UDP PPS | 0 | 0 | 200/200 | 88.46 | yes |
| 4096 / 1024 | IP | 64 prefix | 6000 UDP PPS | 0 | 0 | 200/200 | 77.27 | yes |
| 4096 / 1024 | IP | 8 MAC1 | 49.99 / 50.00 Mbit/s | 0 | 0 | 200/200 | 44.00 | yes |
| 64 / 256 | IP+NAT port | 64 prefix | 49.99 / 50.00 Mbit/s | 472 | 0 | 200/200 | 40.00 | no |
| 64 / 256 | IP | 64 prefix | 49.99 / 50.00 Mbit/s | 644 | 0 | 200/200 | 52.00 | no |

Raising only source credit to 2048 reduced TCP losses but also exposed
aggregate discards. Adding aggregate credit 1024 removed early TCP losses,
yet UDP still lost 321 and 137 packets during migration. Those failed
settings were retained. One zero-client-loss TCP attempt lost 237 noise
datagrams in the generator's fq_codel before the switch. Switch and entry
both counted 1,749,763; that attempt is excluded from capacity qualification,
not described as a switch classifier failure.

Larger credits alone also regressed cold startup under MAC1 noise: first
grants took about 15 and 40 seconds, with 95/200 timely echoes and zero
early-client/NFQUEUE drops. More handshake-shaped junk reached B. That
attempt is retained separately. The independent control quota restored
cold startup without removing transport credit.

## Final policy and repeats

| Burst source / all | Move | Noise | Useful traffic | Client discards | NFQUEUE | Echoes | CPU % | Pass |
|---|---|---|---|---:|---:|---:|---:|---|
| 4096 / 1024 + ctl | IP+NAT port | 64 prefix | 49.99 / 50.00 Mbit/s | 0 | 0 | 200/200 | 37.50 | yes |
| 4096 / 1024 + ctl | IP+NAT port | 64 prefix | 50.00 / 50.00 Mbit/s | 0 | 0 | 200/200 | 40.00 | yes |
| 4096 / 1024 + ctl | IP+NAT port | 64 prefix | 50.00 / 50.00 Mbit/s | 0 | 0 | 200/200 | 42.31 | yes |
| 4096 / 1024 + ctl | IP+NAT port | 64 prefix | 6000 UDP PPS | 0 | 0 | 200/200 | 68.42 | yes |
| 4096 / 1024 + ctl | IP+NAT port | 64 prefix | 6000 UDP PPS | 0 | 0 | 200/200 | 75.00 | yes |
| 4096 / 1024 + ctl | IP+NAT port | 64 MAC1 | 49.97 / 50.00 Mbit/s | 0 | 0 | 200/200 | 54.17 | yes |
| 4096 / 1024 + ctl | IP | 64 prefix | 50.00 / 50.00 Mbit/s | 0 | 0 | 200/200 | 41.67 | yes |
| 4096 / 1024 + ctl | IP | 64 prefix | 49.99 / 50.00 Mbit/s | 0 | 0 | 200/200 | 37.50 | yes |
| 4096 / 1024 + ctl | IP | 64 prefix | 49.99 / 50.00 Mbit/s | 0 | 0 | 200/200 | 40.74 | yes |
| 4096 / 1024 + ctl | IP | 64 prefix | 6000 UDP PPS | 0 | 0 | 200/200 | 76.92 | yes |
| 4096 / 1024 + ctl | IP | 64 prefix | 6000 UDP PPS | 0 | 0 | 200/200 | 78.26 | yes |
| 4096 / 1024 + ctl | IP | 8 MAC1 | 50.00 / 50.00 Mbit/s | 0 | 0 | 200/200 | 33.33 | yes |

All 12 qualified final trials passed: 8 TCP and 4 UDP,
2400/2400 echoes, zero early-client/NFQUEUE/netlink
discards, zero reported UDP loss and peak whole-VM CPU 78.26%.
Every qualified final trial matched sender, switch and entry at 1,750,000 noise
datagrams with complete timing and no switch loss. This includes repeated
IP-only and IP-plus-port changes and both recognizable-junk fixtures.
Noise reaching C averaged 1516 to 1518 datagrams/s.
In both MAC1 trials, the separate control quota reduced forwarding to B to
20.1/s. Transport-shaped noise still reaches B for authentication.
Most offered noise was intentionally discarded. Kernel counters count skbs;
useful UDP PPS is not a measurement of outer AWG wire PPS.
The earlier burst-only series also contains a one-packet loss in the
generator's fq_codel. It had zero client loss, was excluded from capacity
qualification and was repeated under a new trial ID.

The two cold-start checks also passed with no inherited lease: 400/400
echoes, zero early-client/NFQUEUE loss and CPU at most 72.00% including
native startup. They verify bootstrap, without a bulk-capacity claim.

One further MAC1/IP-plus-port workload was interrupted when the host switch
hit its old 20,000 timing-bin assertion. Lab Ethernet stopped even for
ordinary ping. The partial run is retained locally and excluded from all
completed-trial and CPU qualification counts. The switch now evicts its
oldest timing bin from a fixed 4096-bin history; cumulative counters continue.
Native and socket regression tests passed, including bin eviction. After
restarting only the disposable fabric, the interrupted workload and the
last two UDP repeats passed. The table includes both recorded switch versions;
their hashes are in the data. Packet forwarding code was unchanged.

## Trust, limits and rollback

The ordinary parser/batch tests, three exact-mark tests and six agent tests
passed. Mark tests cover type classification, byte order, unrelated mark
bits, packet-ID wrap and send failures. A live old-binary test got
0/3 replies, a rising missing-classification drop counter and no new lease.
Restoring the marked binary recovered connectivity. Final-rule checks retained expiry while A's
helper was paused, recovery after resume, rejection of 200 full ciphertext
replays without a fresh event/lease, and the mutual-TLS certificate-required
alert without a client certificate. Spoofing an already leased tuple still
passes A's cache: one modified packet passed A, was rejected by B and did
not refresh the lease. Larger cold credits also forward more unverified
traffic to B; they do not strengthen authentication or prevent DDoS.

These results cover the local link and proof delays in this series.
WAN-delay emulation, physical GUI clients,
distributed sources, state exhaustion, adaptive attacks and hours-long
operation were not tested here. A sufficiently long proof delay can exhaust
any finite credit. The existing source-spoofing and I1/Jc/camouflage limits
remain. Normal installers do not enable this experiment.

Rollback restored B's original binary/unit/environment, ordinary DNAT,
gateway NAT and client runtime, plus the original console/scheduler/netdev
settings and guard template. Both original profiles passed probes.
Temporary tables and helpers were removed or stopped. All four VMs and
owned host helpers stopped; eleven loopback lab ports were free. Parent
disk, profile, personal-JSON, original binary and prior v1 through v18
report/data hashes matched. Both measured switch versions and the archived
original C source were verified separately. Live servers, the user's VPN and GitHub were
untouched. Raw measurements and captures remain local.
