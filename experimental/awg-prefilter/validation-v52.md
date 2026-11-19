# V52. A separate queue for NAT port changes

English | [Русский](validation-v52.ru.md)

The first forwarded packet from the client's new NAT port took 909 ms to cross A when the shared classifier was paused. With discovery samples on their own queue, the packet crossed A in 111 ms while the shared classifier was still paused. The switch dropped no frames in either run at 25,000 background packets/s.

## The 1.14-second delay in v50

The first packet that A forwarded from the final NAT port spent 1,144.54 ms between ingress and egress. From the first packet the switch saw on that port to the first one A forwarded, 1,184.83 ms elapsed. During that interval A's vCPU ran for 1,116.35 ms. The only wait of at least 5 ms for QEMU's big lock (BQL) lasted 39.30 ms and coincided with a COM1 file write.

The shared NFQUEUE 100 reached its 4,096-packet limit and recorded 1,743 overflows during the run. The original capture gives the packet's total time on A. It has no timestamps at the queue and classifier boundaries. [V51 timing and return-path analysis](validation-v51.md)

## Test setup

Four local QEMU/WHPX VMs each had one vCPU and 1,024 MiB of RAM, with no CPU quota. All runs used file-backed COM1, 25,000 background packets/s across 16 source addresses and 6,000 useful UDP packets/s. The configured RTT was 300 ms with jitter. Both AWG client profiles passed checksum verification. The lab changed the client's IP and NAT port and restarted A's flow helper in each run. In the pause trials it also sent `SIGSTOP` to the queue 100 classifier for about 1.25 s, then automatically resumed it.

We matched packets by UDP source port and AWG nonce at ingress, at NFQUEUE enqueue and classifier callback, and at egress after the Linux queueing discipline. The callback-to-egress times include the configured `netem` delay. The switch clock measures time to B's reply. Windows scheduler ETW covered every load window and reported zero lost events.

## The lab patch

The [optional patch](research/v52-discovery-queue.patch) moves the existing rate-limited discovery sample to NFQUEUE 103. The same classifier runs there in a separate process with `Nice=-5`. It applies the same Header Protection and handshake MAC1 checks. Classified packets skip queue 100 and still pass through the handshake rate limiter when applicable. The sample keeps its per-source and aggregate limits. Sampled packets drop if queue 103 has no listener.

In the disposable lab, run `git apply --check experimental/awg-prefilter/research/v52-discovery-queue.patch` from the repository root before applying the patch to the escrow rules. Build `prefilter-handshake` and start a second instance on A with `--vm-test --queue 103`, the same lab key file as queue 100 and a nice value of −5. Verify the listener in `/proc/net/netfilter/nfnetlink_queue` and check the rules with `nft -c` before loading them. Restore the lab rules that use queue 100, or remove the test rules, before stopping 103. [Forward escrow setup](flow-confirmation/README.md#optional-forward-escrow)

## Results

The first-packet columns follow the first packet from the final port that A forwarded to B. The maximum is over the first 12 matched packets from that port in egress order. The reply column starts when the switch first sees the final port and ends at B's first full-size reply to it.

| Run | Queue | First classifier wait (ms) | First packet on A (ms) | Max classifier wait (ms) | First B reply (ms) | Missing useful UDP | Switch drops |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Normal control | 100 | 6.28 | 125.86 | 692.10 | 320.62 | 0 | 0 |
| Normal, patched | 103 | 9.89 | 166.33 | 254.60 | 235.12 | 1,157 | 0 |
| Queue 100 paused, control | 100 | 798.60 | 909.43 | 809.19 | 1,188.21 | 6,948 | 0 |
| Queue 100 paused, patched | 103 | 21.09 | 144.29 | 132.44 | 236.17 | 5,862 | 18,531 |
| Queue 100 paused, patched repeat | 103 | 27.50 | 111.46 | 50.68 | 203.03 | 104 | 0 |
| Normal, patched repeat | 103 | 170.36 | 273.81 | 222.61 | 440.69 | 0 | 0 |

In the normal control, one early packet waited 692.10 ms to reach the classifier. The median time from callback to egress for the first 12 packets was 149.60 ms.

With queue 100 paused, the control classified the first forwarded packet 99.55 ms after that queue resumed. In the patched repeat with all 1,750,000 background packets delivered to A, the first packet left A 702.54 ms before queue 100 resumed. Queue 100 logged 2,405 overflows. Queue 103 peaked at 96 packets with zero overflows. On A, neither of these runs recorded a main-thread BQL wait of 5 ms or more during load.

The first patched pause run also forwarded a packet while queue 100 was stopped. In that run a COM1 file write held the BQL for about 461 ms and the switch dropped 18,531 frames, so the delivery comparison uses the repeat.

With the patch, both normal runs reduced the longest classifier wait in the sample. Time to the first reply from B varied from 235 to 441 ms, compared with 321 ms in the control. One normal patched run missed 1,157 of 360,000 useful UDP packets. The repeat delivered all of them.
