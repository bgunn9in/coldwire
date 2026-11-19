# V51. The 8,278 missing UDP packets in v50 run 5

English | [Русский](validation-v51.ru.md)

The v50 switch dropped no frames. A took more than a second to forward a packet from the latest NAT port to B. During the delay, B continued sending replies to previous ports. The capture shows that B later resent only part of that traffic to the latest port.

## What the original capture shows

The inner capture at B contains all 360,000 UDP sequence numbers. The capture at the client and its receiver both count 351,722. Neither capture dropped records. All 8,278 missing numbers fall in two consecutive sender time bins. The longest continuous run was 7,736 packets, from 152,137 to 159,872. The client's inner capture has a 1,813.47 ms delivery gap around the port changes.

The switch uses one clock for client → A, A → B and B → A. It first saw a client packet from the latest port 1,184.83 ms before it saw A forward a packet from that port. Matching the first forwarded packet by length and nonce puts its transit through A at 1,144.54 ms. The first full-size return packet from B for the new port appeared 1,262.57 ms after the switch first saw the client use that port.

In that interval B sent 11,757 full-size frames to older ports, including retransmissions. The capture first saw 7,569 unique encrypted packets on those ports after the final port change. It later saw 2,554 of them on the new port. The original tap did not capture A → client or map ciphertext to inner UDP sequence numbers, so it cannot assign all 8,278 missing numbers to individual outer packets.

B's regular reply cache holds packets for up to 500 ms. The deferred retry has a separate time limit for packets it already selected. Of 3,007 unique full-size packets first seen on an old port in the 500 ms before B started replying to the latest port, 2,553 appeared again on the latest port. Only one of 8,599 older packets did.

## Queues and ETW

During the 1,184.83 ms gap before A forwarded the new port, A's vCPU ran for 1,116.35 ms, spent 9.92 ms ready and 58.54 ms waiting. The only main-thread BQL wait of at least 5 ms took 39.30 ms and overlapped a COM1 file write. The independent Windows clock observer had a maximum sample gap of 50.76 ms during that interval.

NFQUEUE 100 reached its limit of 4,096 packets, with 1,743 queue drops recorded in the run. Queues 101 and 102 recorded 2,735 and 2,734 drops while sending packets to userspace. Those counters measure the client-to-B direction. They show pressure on A during the port change, but the original trace lacks per-packet timestamps at each queue boundary.

## Two local repeats

The switch recorded up to 96 bytes per captured frame, including the return path from A to the client. Matching length and nonce linked frames received from B with those forwarded by A. The four QEMU 11.1.3/WHPX VMs each had one vCPU and 1024 MiB, without CPU quotas. Both runs used file-backed COM1, unchanged client profiles, 25,000 background packets/s, 6,000 useful UDP packets/s and a nominal 300 ms RTT with jitter. ETW covered both load windows and reported zero lost events.

| Run | Time from first client packet on the final port to first full-size B reply on that port | Switch drops | Missing useful UDP |
| --- | ---: | ---: | ---: |
| v50 run 5 | 1,262.57 ms | 0 | 8,278 |
| v51 repeat 1 | 296.91 ms | 0 | 0 |
| v51 repeat 2 | 284.34 ms | 544 | 331 |

In repeat 1, A forwarded 5,516 full-size frames to older client ports, matched by nonce. All 6,130 unique full-size packets first seen on older ports before the first reply on the latest port later appeared on the latest port. The application received all 360,000 packets.

Repeat 2 delivered 1,749,526 of the 1,750,000 background packets to A. Its switch losses exclude it from the zero-drop comparison. After collecting its results, the launcher stopped A after the VM exceeded the shutdown wait and verified that the local lab ports were free.

[Configure the return-path capture](lab-switch/README.md#record-switch-and-host-timing)
