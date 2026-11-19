# V53. UDP receive buffer overflow on the return path

English | [Русский](validation-v53.ru.md)

A burst of retransmissions after NAT roaming filled the client's AmneziaWG UDP receive buffer in one control run. Pacing return traffic on A eliminated receive buffer overflows in two repeats. Both delivered all 360,000 test datagrams.

## The 1,157 missing datagrams in v52

B's capture counted all 360,000 test datagrams. The client's inner capture counted 358,843. The switch and NFQUEUE 103 reported zero drops. B replayed all 5,795 unique full-size frames originally sent to older ports between the first port change and the first reply on the final port. The switch saw matching copies at A's egress to the client on that final port.

A sent as many as 1,142 full-size frames to the final port in 10 ms. Two loss-free v52 runs peaked at 663 and 651 frames in that window size. We decoded transport counters in the lab captures using the lab's header protection key. In A's egress capture, a previously unseen counter lagged the highest observed counter by at most 7,797, within the client's 8,128-counter window. This was the order at A's egress. The original run recorded no client socket counters, so its 1,157 missing datagrams cannot be matched to individual socket drops. [V52 measurements](validation-v52.md)

## Reproducing the overflow

The four QEMU/WHPX VMs had one vCPU and 1,024 MiB each, without CPU quotas. They used file-backed COM1. Each run used 25,000 background packets/s from 16 addresses and 6,000 test UDP datagrams/s, with a configured RTT of 300 ms and jitter. The lab changed the client's IP or NAT port three times and restarted A's flow helper. The NFQUEUE 103 classifier ran throughout.

A probe in the client's network namespace read `Udp.RcvbufErrors` and the drop counter for the stock AmneziaWG UDP socket. We captured encrypted datagrams at the client's virtual Ethernet interface before socket delivery and counted decrypted test datagrams by sequence number.

In the first control run, `Udp.RcvbufErrors` and the socket drop counter both increased by 553 between samples taken 328 and 529 ms after the last port change. The socket's receive queue used about 8.6 MiB at the second sample. The loss count for test datagrams was 511. Socket drops count encrypted datagrams and can include duplicates and control traffic.

## Return-path pacing

The [lab script](research/v53-return-pacing.sh) puts matching return traffic in a FIFO `tc tbf` queue on A after NAT. The filter matches A's source address and the AWG UDP source port. The token bucket uses 260 Mbit/s with a 32 KiB burst and an 8 MiB queue limit. Traffic from A to B keeps its own `netem` band. The limiter preserves order within the return queue.

From the repository root on the disposable entry VM, run `sudo sh experimental/awg-prefilter/research/v53-return-pacing.sh` in place of the usual A-side `netem` setup. The script checks for the lab hostname `kit-entry` and replaces the root qdisc on `enp0s3`. The lab teardown restores the default test qdisc, removes the experimental packet hooks and checks ordinary DNAT with both original client profiles.

## Results

All 1,750,000 background packets reached A in each run. Windows scheduler ETW covered every load window with zero lost events. The switch and the client-side captures reported zero drops. Checksums verified the two client profiles and the AmneziaWG binary.

| Run | Missing test datagrams out of 360,000 | UDP buffer errors / socket drops | Peak full-size frames at client in 10 ms | Return transit through A, p95 (ms) | TBF drops |
| --- | ---: | ---: | ---: | ---: | ---: |
| Control 1 | 511 | 553 / 553 | 935 | 36.40 | — |
| Control 2 | 0 | 0 / 0 | 752 | 46.62 | — |
| TBF, first full run | 0 | 0 / 0 | 265 | 219.71 | 0 |
| TBF, repeat | 0 | 0 / 0 | 261 | 190.63 | 0 |

Return transit uses switch timestamps for full-size frames on the final NAT port during the first 1.5 s after B's first full-size reply. The maximum time across A was 225.30 ms in the first full TBF run and 196.39 ms in the repeat. The queue forwarded 374,433 and 374,121 packets in those runs. The second control also completed without loss. The pacing results cover this load and lab configuration.
