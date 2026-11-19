# V44. TCP and AF_UNIX on the same QEMU stream backend

English | [Русский](validation-v44.ru.md)

The four Debian 13 VMs ran on Windows with QEMU 11.1.3/WHPX. Each had one vCPU and 1024 MiB with no CPU quota. The sender offered 25,000 background packets/s across 16 addresses and 6,000 useful UDP packets/s at a nominal RTT of 300 ms with jitter. The clients retained the same profiles and binary. The four paired runs used the same instrumented QEMU build and changed only the address type of `-netdev stream`. A separate AF_UNIX run used QEMU without the probes.

| Run | Noise received at A | Max. queued write gap to A, ms | Switch drops | Missing UDP | Missing ping |
| --- | --- | --- | --- | --- | --- |
| stream-tcp-a | 1750000 | 16.3 | 0 | 620 | 6 |
| stream-tcp-b | 1656644 | 2269.8 | 114146 | 25881 | 2 |
| stream-unix-a | 1750000 | 47.3 | 0 | 1329 | 31 |
| stream-unix-b | 1750000 | 89.8 | 0 | 849 | 22 |
| stock-unix-a | 1750000 | 15.6 | 0 | 0 | 0 |

Both paired AF_UNIX runs delivered all 1,750,000 background packets to A. NFQUEUE losses still occurred inside A. The stock-QEMU AF_UNIX check delivered all 360,000 useful UDP packets and all 100 ping replies. TCP A missed the target offered rate, and TCP B lost some background frames before A. Both TCP runs failed the load qualification used for the filter comparisons.

## TCP B receive pause

QEMU on A went 2.343 seconds between successful reads. A's guest RX counter stayed flat for 2.259 seconds. The switch's output toward A made no progress for 2.270 seconds, and that port accounted for all 114,146 switch drops. The last QEMU read before the pause preceded the switch's last successful write by about 111 ms. Twenty-two successive TCP snapshots recorded a closed send window with no bytes in flight. The window reopened after reads resumed.

The QEMU timestamps bound time spent with the read watch detached to 65.1 ms during the long gap. The main-loop wait logger recorded no intervals of 100 ms or more in that gap. A separate `FIONREAD` run recorded 34 samples and a longest read gap of 130.1 ms. That run missed the first changed-port packet required to trigger the test's `SIGKILL` step. The probe has no observation of the long event.

The failure can occur with TCP on `stream`. The first trigger of the original 4.77-second pause in v42 remains unknown. [TCP_INFO_v0 fields](https://learn.microsoft.com/en-us/windows/win32/api/mstcpip/ns-mstcpip-tcp_info_v0)

[Lab switch](lab-switch/README.md) · [Results JSON](results-v44.json)
