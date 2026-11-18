# V42. UDP measurement without a packet capture

English | [Русский](validation-v42.ru.md)

The lab receiver now reports missing sequences grouped by the sender's scheduled second. It already tracked each received sequence. The new report is computed from that record after the run, so it adds no per-packet processing. A complete local UDP capture is still useful when timestamps or a forwarding boundary matter. For a delivery count, the receiver can supply an independent total.

## What we compared

Four Debian 13 VMs ran with one vCPU and 1024 MiB each under QEMU/WHPX. All runs used 25,000 noise packets/s from 16 IPs, batches of up to 4096, and 6000 useful UDP packets/s from B to the client at 1200 bytes each. The link between A and B used a delay of 150 ± 30 ms each way. The client changed IP and NAT port three times. A's helper received SIGKILL at the first change. The sender, receiver, profiles, guard rules and queue sizes were the same in all four runs.

The sequence was capture, application only, application only, capture. Here application only means measuring useful UDP at the sender and receiver while omitting the two guest UDP captures. ICMP observation, the switch's short WAN capture, per-source noise counters and the VM sampler ran in both modes. To qualify, the lab had to receive exactly 1,750,000 noise packets from the expected sources, satisfy the rate checks, and have no switch drops. Capture runs also had to pass the capture checks.

| Mode | Qualified | Missing UDP | Switch drops | Missing ping | Maximum RTT, ms |
|---|---|---:|---:|---:|---:|
| Capture / A | no | 41309 | 158959 | 69 | excluded |
| Application / A | yes | 0 | 0 | 0 | 1244.017 |
| Application / B | yes | 0 | 0 | 0 | 1306.374 |
| Capture / B | yes | 0 | 0 | 0 | 1265.900 |

## What failed

The first capture run lost 158,959 Ethernet frames at the switch. The output toward A accounted for 155,829, and the one toward the client for 3130. A's RX counter stayed flat for a run of samples lasting about 4.77 seconds. The sampler kept running, and neither NFQUEUE nor C logged resource drops. A received 1,627,120 of the 1,750,000 noise packets. The valid captured sequence counts and receiver's missing bins agreed, including the 41,309 useful UDP packets that failed to reach the application. The excluded run cannot measure the effect of the filter at the requested load.

The two application-only runs delivered all 720,000 useful packets and 200 ping replies. The highest RTT was 1.306 s. The second capture run also passed without loss. Mean client VM CPU was 11.5 to 11.6% without capture and 17.8% in the qualified capture run. B used 32.4 to 32.6% and 37.6%, respectively. The lighter mode is sufficient for counting delivery. These trials do not establish the cause of the receive stall in QEMU or prove that capture triggered it.

The receiver records scheduled seconds and cumulative delivery. It does not measure per-packet delay or place a missing packet on a particular forwarding hop. Keep per-packet capture for those questions.

## Verification

The updated probe builds with warnings treated as errors and passes its self-test on both B and the client VM. Plain DNAT and stock B were restored after the experiment. Both original profiles connected before the VMs were shut down.

[Results JSON](results-v42.json) includes the qualification flag and both observer outputs for each applicable run. [Receiver patch](research/v42-retained.patch)
