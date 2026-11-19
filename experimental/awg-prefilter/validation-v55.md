# V55. Return replays after NAT port changes

English | [Русский](validation-v55.ru.md)

B defers recovery traffic during a series of authenticated moves so fewer copies go to intermediate ports. A cache-advance guard can release a pending replay early. With that mode and a 2,048-packet `awg0` queue on B, all four runs delivered all 360,000 test datagrams, including the runs that killed and restarted A's helper.

## Test setup

The four local QEMU/WHPX VMs each had one vCPU and 1,024 MiB of RAM, with no CPU quota. COM1 used a ring buffer and the host switch used 16 MiB output queues. The client access model used independent queues in each direction for 100/100 or 150/150 Mbit/s. A and B used 150 ms of configured delay with 30 ms of jitter in each direction between them.

The background generator sent 25,000 packets/s from 16 sources. B sent 360,000 test UDP datagrams downstream at 6,000/s. The client gateway changed the client's IP or NAT port three times. In the fault runs, the first move coincided with a `SIGKILL` of A's helper. Checksums verified the original AmneziaWG binary and both client profiles. Windows scheduler ETW covered the full background load.

Transit through A uses the switch timestamps for matching B-to-A and A-to-client frames. On the access segment, captures before its input queue and at the virtual interface before the client UDP socket use the same guest clock. The sum is calculated per matched frame before taking the p95. The sample covers 1.5 s of full-size frames from B's first reply on the final port. [V54 measurement method](validation-v54.md#modeled-100-and-150-mbits-access-links)

## Replays to intermediate ports

In the four loss-free v54 runs, the switch recorded 6,105–6,465 full-size replays to old ports during a series of moves. It also saw 5,978–6,946 replays to the final port. The counts use repeated length and nonce pairs on the B-to-A path. At 100 Mbit/s, about 6,400 additional frames of roughly 1.3 KiB take about 0.68 s to transmit.

Two new controls with the 260 Mbit/s A limit missed 359 and 547 test datagrams. The switch, TBF and client socket showed zero drops. In the 150/150 control, 548 unique full-size frames sent to older ports never appeared on the final port. The comparison below includes the loss-free v54 controls with the same access model.

## Separate queues by port

In this experiment A used `fq` for different NAT ports and paced its return traffic at the access rate. On 150/150 it delivered all datagrams. The access p95 fell to 0.23 ms, while A's p95 increased to 723.65 ms. The p95 of their sum was 723.71 ms, up from 604.54 ms in the loss-free v54 control. The wait moved to A.

On 100/100, the access p95 was 1.56 ms with 9,337 test datagrams missing. The first packet forwarded from the new port waited about 1.04 s for the NFQUEUE 103 classifier. B replayed only 2,377 of the 12,873 full-size frames sent to previous ports. This run leaves the effect of `fq` on delivery unresolved.

## Coalescing replays on B

On the disposable B VM, set `COLDWIRE_LAB_RETURN_SETTLE=1` alongside `COLDWIRE_LAB_RETURN_REPLAY=1` and the existing proof socket. B can wait up to 320 ms to coalesce successive authenticated moves and retargets the pending replay after each move. It keeps the original snapshot expiry and rate limits. Ordinary traffic continues to flow. The tests exercise retargeting, packet order, the expiry bound and early release. [Return recovery setup](flow-confirmation/README.md#optional-return-recovery)

In the first 100/100 run, the switch saw zero replays to intermediate ports. The access p95 was 485.49 ms and the sum was 600.19 ms. Six datagrams were missing. The client-side capture showed six previously unseen full-size transport counters more than 8,128 behind the highest counter. The socket and queues showed zero drops.

The revised mode can release a replay early when the cache's insertion sequence advances by 7,400 from the oldest retained packet. This sequence counts packets for all peers, which leaves a conservative margin for a single peer. B still checks the authenticated endpoint and key epoch before sending.

## Drops before encryption

The first runs with the early-release guard delivered all test datagrams. Later runs on 100/100 and 150/150 missed 284 and 376. The switch, TBF and client socket showed zero drops. In the 100/100 repeat, the 284 missing sequence numbers were consecutive. All full-size frames B forwarded to the final port in that interval matched frames at the client virtual interface before socket delivery.

A diagnostic build mapped test datagram numbers to AWG counters before encryption. In its 150/150 run, the 500-packet `awg0` queue on B recorded 111 transmit drops and the client missed 111 test datagrams. Of the 92 missing sequence numbers covered by the mapping, none reached encryption. The same diagnostics showed zero losses in a 100/100 run.

### Loss-free runs with the 500-packet queue

| Access (Mbit/s) | Mode | Access p95 (ms) | p95 of A plus access (ms) | Missing UDP |
| --- | --- | ---: | ---: | ---: |
| 100/100 | v54 control, A at 260 Mbit/s | 1,156.46 | 1,239.61 | 0 |
| 100/100 | Coalescing with early release | 491.74 | 601.43 | 0 |
| 100/100 | Same mode with B diagnostics | 482.12 | 584.81 | 0 |
| 150/150 | v54 control, A at 260 Mbit/s | 472.58 | 604.54 | 0 |
| 150/150 | Coalescing with early release | 307.09 | 512.69 | 0 |

## The 2048-packet queue on B

On the disposable B VM, run `sudo ip link set dev awg0 txqueuelen 2048` after creating the tunnel and before starting the load. Check the length and counters with `ip -s -j link show dev awg0` before and after the run. Coalescing and early release stay enabled. The queue setting applies to the lab interface.

Each run delivered all 1,750,000 background packets to A at 25,000 packets/s. ETW covered the full load with zero events lost. The first pair tested roaming while A's helper kept running. The second pair restarted the helper after `SIGKILL`, as in the earlier diagnostic series.

| Access (Mbit/s) | Mode | UDP delivered | `awg0` drops | Access p95 (ms) | p95 of A plus access (ms) |
| --- | --- | ---: | ---: | ---: | ---: |
| 100/100 | Roaming | 360,000 / 360,000 | 0 | 553.00 | 644.29 |
| 150/150 | Roaming | 360,000 / 360,000 | 0 | 219.16 | 349.63 |
| 100/100 | Roaming with A helper restart | 360,000 / 360,000 | 0 | 525.95 | 589.61 |
| 150/150 | Roaming with A helper restart | 360,000 / 360,000 | 0 | 377.41 | 583.48 |

The transmit-drop counter on B and the qdisc, switch, access-queue and client-socket drop counters were zero in all four runs. Each run logged all 40,001 test datagrams in the diagnostic range before encryption. The results cover this load and these rapid port changes.
