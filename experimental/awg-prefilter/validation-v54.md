# V54. Return-path queue latency on A

English | [Русский](validation-v54.ru.md)

Increasing the return-path limit on A from 260 to 360 Mbit/s cut the measured p95 transit time through A. All four runs with modeled 100/100 and 150/150 Mbit/s client links delivered all 360,000 test datagrams. Most of the delay during recovery was on the client link.

## Test setup

Four local QEMU/WHPX VMs each had one vCPU and 1,024 MiB without CPU quotas. The sender on B sent 6,000 test UDP datagrams/s for 60 s. A received traffic from a background generator configured for 25,000 packets/s from 16 addresses for 70 s. Both directions between A and B used 150 ms of configured delay with 30 ms of jitter. In each trial the lab changed the client's IP or NAT port three times and killed A's flow helper to exercise its restart. The NFQUEUE 103 classifier stayed enabled. The two AmneziaWG client profiles and the client binary passed checksum checks. Windows scheduler ETW captured the load windows.

The trials used a 32 KiB burst and an 8 MiB limit for the return queue on A. Time through A is the interval between the switch seeing a frame from B to A and seeing the matching frame from A to the client. Frames were matched by length and nonce. The sample starts at B's first full-size reply on the final NAT port and covers the next 1.5 s. A zero-loss run needed all 1,750,000 background packets at A, all test sequence numbers at the receiver, and zero drops in the socket, queues, switch and captures.

## Early runs with losses

The first 260 Mbit/s run missed 10,225 test datagrams. TBF, the client socket and the switch reported zero drops. The first forwarded packet from the final NAT port waited 1,323.81 ms for the NFQUEUE 103 classifier. B's first full-size reply appeared 1,559.90 ms after the switch first saw that port. B replayed 2,504 of the 13,448 unique full-size frames that had gone to old ports. Many of those frames aged out of recovery. The low p95 in this run reflects a smaller set of returned packets.

At 400 Mbit/s, p95 through A was 102.16 ms with 70 missing test datagrams. TBF, the socket and the switch still reported zero drops. Of 6,903 frames on previous ports in the recovery window, 27 never appeared on the final port. The capture leaves the cause of the remaining losses unresolved.

At 480 Mbit/s, the switch dropped 25 and 236 frames in two runs. The receiver missed 22 and 227 test datagrams. The 4 MiB switch output queue toward A filled in both cases. All background packets reached A. The first ring-buffer control at 260 Mbit/s also hit the switch queue limit and lost 477 frames there.

## Matched runs without a client access limit

These runs used ring-buffer COM1. The control repeat and both 360 Mbit/s runs met the zero-loss criteria. The faster rate reduced p95 through A by 34–56%. ETW reported zero lost events during load.

| A limit | Missing test datagrams | p95 through A (ms) | Maximum through A (ms) | Peak full-size frames at client per 10 ms |
| --- | ---: | ---: | ---: | ---: |
| 260 Mbit/s, control repeat | 0 | 190.79 | 198.33 | 264 |
| 360 Mbit/s, run 1 | 0 | 125.56 | 128.74 | 357 |
| 360 Mbit/s, run 2 | 0 | 83.73 | 86.79 | 352 |

On the disposable entry VM, run `sudo sh experimental/awg-prefilter/research/v53-return-pacing.sh 360` from the repository root to select 360 Mbit/s. The script checks the lab hostname and replaces the root qdisc on `enp0s3`. Omit the argument to get the 260 Mbit/s control. [Lab script](research/v53-return-pacing.sh)

## Modeled 100 and 150 Mbit/s access links

The lab gateway outside the clients' network namespaces used two independent token buckets. An IFB shaped the download and a separate egress class shaped the upload. Each direction used a 32 KiB burst and a 16 MiB FIFO. The filters matched outer AWG UDP traffic. The background generator sent directly to A. The useful UDP load ran downstream. The upstream bucket carried tunnel and ICMP traffic during the test.

For all four access-link trials, the host switch used a 16 MiB output queue in place of the 4 MiB queue used in the earlier runs. On the client segment, captures before the IFB and at the client's virtual Ethernet interface used the same guest clock. The table uses frames with a unique match at all four points. The last latency column gives the p95 of the per-frame sums. It excludes the interval between A's egress at the switch and the gateway's first capture of that frame.

| Client link (Mbit/s) | A limit (Mbit/s) | Matched frames | p95 on A (ms) | p95 on client segment (ms) | p95 of sum (ms) | Missing test datagrams |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 100/100 | 260 | 8,295 | 160.24 | 1,156.46 | 1,239.61 | 0 |
| 100/100 | 360 | 8,634 | 100.85 | 1,139.23 | 1,179.45 | 0 |
| 150/150 | 260 | 8,314 | 173.77 | 472.58 | 604.54 | 0 |
| 150/150 | 360 | 8,328 | 84.96 | 522.22 | 579.81 | 0 |

All four runs met the zero-loss criteria, including both access queues. ETW covered the full load without losing events. The two 100/100 runs sent different numbers of return frames. Feeding either captured input into a two-bucket calculation gave the same p95 sum for 260 and 360 Mbit/s on A. The modeled sums were 1,235.71 ms for the first capture and 1,172.89 ms for the second. The measured difference between runs therefore includes variation in the traffic entering A. The access-link numbers describe the local FIFO model and its buffer sizes.
