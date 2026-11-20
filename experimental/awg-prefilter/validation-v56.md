# V56 lab validation

English | [Русский](validation-v56.ru.md)

Four short controls delivered all 360,000 UDP datagrams with a 2,048-packet `awg0` queue on B. The tests covered single IP/NAT-port changes and a three-change series with A's flow helper restarted after `SIGKILL`.

## Short controls

Each of the four local Debian 13 VMs had one vCPU and 1,024 MiB with no CPU quota. QEMU/WHPX used AF_UNIX stream networking, Virtio and ring-buffered COM1. The A–B path had a configured 300 ms RTT with jitter. The access links were shaped in both directions. A paced return traffic at 260 Mbit/s and B used the v55 replay coalescing mode. Both native client profiles and the client binary matched their original checksums.

Every short control delivered all 1,750,000 background packets to A at approximately 25,000 packets/s. B sent 6,000 useful 1,200-byte UDP datagrams per second for 60 seconds. The switch, B's tunnel queue, the access queues and the client socket recorded zero drops. Windows scheduler ETW covered the full load in each control with zero lost events.

| Access (Mbit/s) | Change | UDP received | Access p95 (ms) | A plus access p95 (ms) | UDP delay above steady state, p95 (ms) |
| --- | --- | ---: | ---: | ---: | ---: |
| 100/100 | Single | 360,000 | 241.66 | 267.15 | 701.88 |
| 150/150 | Single | 360,000 | 72.61 | 83.21 | 605.94 |
| 100/100 | Series, A helper restart | 360,000 | 524.65 | 623.99 | 1,211.99 |
| 150/150 | Series, A helper restart | 360,000 | 160.19 | 234.21 | 1,000.72 |

The access metric matches full-size encrypted packets by their transport header between the client's WAN and virtual Ethernet interfaces. It uses the first 1.5 seconds of full-size return traffic on the final port. The A-plus-access metric adds transit through A for each matched packet. The application metric compares delivery time around the move to the median in the same run before the move.

Four early attempts missed the single-move capture because the tap still expected the first port from the three-change sequence. A fifth attempt opened several captures on recurring packets from the selected port. These attempts are excluded from the table. The single-move control uses a one-shot tap on port 42503. The repository switch exposes that trigger as `--single-move`. [Lab switch options](lab-switch/README.md#record-switch-and-host-timing)

## Classifier and endpoint timing

The archived v55 FQ run lost 9,337 useful UDP datagrams. A's first forwarded packet from the final port spent 1,037.28 ms between guest ingress and the NFQUEUE 103 callback. Over that interval the sampled queue depth grew from 178 to 648 packets. Softirq accounted for about 79–92% of the CPU ticks in the overlapping guest samples. The samples locate the wait before the callback. [V55 results](validation-v55.md)

On a v56 diagnostic run at 150/150, the slowest of the first 12 forwarded packets from the final port waited 52.69 ms before the callback. The guest trace recorded 35.64 ms in NET_RX softirq during that wait. It shows the classifier switched out while runnable and switched back in before the callback. Submitting the verdict took under 1 ms after the callback. ETW recorded 191.68 ms of running time and 3.09 ms ready time for A's vCPU over the corresponding 204.45 ms interval from switch ingress to switch egress.

B recorded the three committed endpoints in that run. It selected 6,141 ciphertext packets for replay to the final endpoint 214.92 ms after committing it. The 7,400-packet cache advance guard triggered before the 320 ms timer. The switch observed zero repeats to an intermediate port and all 360,000 useful datagrams reached the client. The archived v55 switch capture counted 4,436 repeats on an intermediate port, starting 189.69 ms after the first full-size traffic to that port and 85.06 ms before the first full-size traffic to the final port. This older capture records traffic on the wire. The v56 diagnostic logs the committed endpoint and the specific replay trigger on B.

At 100/100 with FQ on A, the slowest of the first 12 forwarded packets waited 58.55 ms for NFQUEUE 103. B's timer fired on the intermediate endpoint 10.44 ms before the final endpoint was committed. The switch recorded three repeats on the intermediate port. The next attempt started 249.20 ms after the final commit. One test datagram reached the client's virtual Ethernet interface with a counter 8,318 behind the highest observed counter for that key, outside the stock 8,128-packet replay window. It was the only datagram missing from the application. FQ put the wait on A again. The access p95 was 1.24 ms, and the p95 across A and the access link was 651.31 ms.

Follow-up runs changed one setting at a time while keeping the same load, 2,048-packet queue, and A helper restart. Raising the discovery service's `CPUWeight` to `1000` with FQ shortened the longest callback wait among the first 12 from 58.55 to 11.13 ms in that run. Extending the quiet period after a retarget from 320 to 350 ms also delivered all datagrams on the FQ 100/100 and TBF 150/150 runs. The cache advance guard fired before the timer in both, at 182.96 and 177.51 ms after the last commit. These two retarget tests give no timing evidence for adopting 350 ms. The tested lab profile retains TBF at 260 Mbit/s on A and the v55 coalescing settings on B.

With TBF on 100/100, the higher CPU weight also delivered all 360,000 datagrams. The longest classifier wait was 9.50 ms, compared with 63.10 ms in the TBF 100/100 restart control. The p95 through A and the access link was 598.76 ms, compared with 623.99 ms. To reproduce that trial on the lab entry VM, run `sudo systemctl set-property --runtime cw52-discovery.service CPUWeight=1000` after starting the classifier. This changes the service's share of CPU time under contention. The 1.04 s callback wait from v55 did not recur in the v56 runs, so the new comparisons establish an improvement in the observed waits only.

## Persistent queue on the lab exit

The [example udev link file](flow-confirmation/80-coldwire-lab-awg0.link.example) applies to `awg0` on the guest named `kit-exit`. Install it on that guest before creating the interface.

```sh
sudo install -D -m 0644 experimental/awg-prefilter/flow-confirmation/80-coldwire-lab-awg0.link.example \
  /etc/systemd/network/80-coldwire-lab-awg0.link
sudo udevadm control --reload
# After the lab AWG service creates awg0:
sudo udevadm settle --timeout=10
cat /sys/class/net/awg0/tx_queue_len
udevadm info -q property -p /sys/class/net/awg0 | grep '^ID_NET_LINK_FILE='
```

The expected length is `2048` and the expected link file is `/etc/systemd/network/80-coldwire-lab-awg0.link`. The setting is applied when udev first sees each instance of the interface. Remove the installed example and reload udev before creating the next interface to return to the lab default. [systemd.link(5)](https://www.freedesktop.org/software/systemd/man/249/systemd.link.html)

The queue measured 2,048 packets after a cold start, after recreating `awg0`, and after an ordinary `systemctl reboot` of B followed by the lab bringing up `awg0`. The reboot with the original WHPX test binary stopped after GRUB loaded the initrd and QEMU logged an XSAVE error. The reboot with the WHPX partition-reset patch returned a new Linux boot ID over SSH in 15.75 seconds. Recreating the interface again after that boot selected the same link file and queue length. Both native clients passed the connectivity check. [Earlier WHPX investigation](../../docs/validation-lts.md#whpx-diagnosis-and-local-repair)

## Two clients over 15 minutes

On 100/100, A received all 22,500,000 background packets from 16 sources in 900 seconds. Both native clients received 3,000 useful UDP datagrams/s for 888 seconds. The lab applied 31 simultaneous IP and NAT-port changes to both clients in 15 groups, alternating a series of three changes with single changes. This run used the same TBF, queue length, and v55 replay settings as the short controls.

| Client | UDP received / sent | ICMP replies after 1 s | ICMP RTT p95 (ms) | Max. ICMP RTT (ms) |
| --- | ---: | ---: | ---: | ---: |
| 1 | 2,664,000 / 2,664,000 | 196 | 1,465.58 | 2,083.05 |
| 2 | 2,664,000 / 2,664,000 | 202 | 1,395.85 | 1,907.57 |

All 1,500 ICMP probes per client received a reply. They ran around the changes, so the RTT percentiles describe those windows. The useful UDP streams had zero duplicates. The switch, B's tunnel, both access queues and both client UDP sockets recorded zero drops. The 101.61-second ETW trace at the start included the first two groups of changes and had zero lost events. Application and queue counters cover the full run.

The `udp-load.c` helper accepts optional packets-per-second and duration arguments. The sender and receiver must use the same values. For this run, each stream used 1,200-byte payloads and `3000 888`. A Linux guest build with strict compiler warnings and the built-in self-test passed on B and the client VM.
