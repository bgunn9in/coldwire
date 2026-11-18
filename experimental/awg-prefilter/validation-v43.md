# V43. QEMU receive stalls and the lab switch's AF_UNIX mode

English | [Русский](validation-v43.ru.md)

The lab switch now supports an AF_UNIX link to QEMU. Two runs on that link delivered all 720,000 useful UDP packets and 200 ping replies. The longest gap between writes on any queued switch port was 25.2 ms. We did not reproduce the original 4.77-second receive stall with diagnostics enabled, so its precise cause remains unknown.

## Where the traffic stopped

In the failed v42 run, the switch continued to receive noise and B continued to send while A's RX counter stood still. The guest sampler kept running. The stall was downstream of the switch's input, but that run had no Windows TCP, QEMU socket or Virtio trace.

In v43 we recorded when QEMU stopped and resumed reading, how long its main loop waited, and what Winsock reported while output was queued. One smaller failure produced a 419.3 ms interval between reads on A, with at most 2.23 ms of disabled read polling over that interval. The diagnostic logged no Windows poll or lock-acquisition interval of 100 ms or more during the load. In another run the switch could not advance its client output for 859 ms even though the TCP send window was open. It had about 1.10 MB of unacknowledged data and recorded retransmissions. Twenty-three direct nonblocking write attempts during a separate run all returned `WSAEWOULDBLOCK`. Skipping the `select` readiness check did not clear the backpressure. [Windows TCP_INFO_v0 fields](https://learn.microsoft.com/en-us/windows/win32/api/mstcpip/ns-mstcpip-tcp_info_v0)

As a calibration, QMP stopped the local A VM for about 758 ms. QEMU reported a 752 ms read pause and the switch observed a zero TCP window. All useful UDP arrived after the VM resumed. This known stop produced a different signal from the later open-window stall.

## AF_UNIX runs

The four Debian 13 guests ran on Windows with QEMU 11.1.3/WHPX, one vCPU and 1024 MiB each, with no CPU quota. The lab offered 25,000 noise packets/s from 16 addresses and 6,000 useful UDP packets/s with 1200-byte payloads. The same clients changed IP and NAT port under a nominal 300 ms RTT. One AF_UNIX run followed a cold boot. Both used the existing Virtio interfaces and queue sizes.

| Run | Load qualified | Switch drops | Missing UDP | Missing ping | Max RTT, ms |
|---|---|---:|---:|---:|---:|
| TCP, first diagnostic run | no | 1542 | 1103 | 0 | 1272.734 |
| TCP, diagnostic repeat | yes | 0 | 0 | 0 | 1289.361 |
| TCP, window diagnostics | yes | 0 | 0 | 0 | 1233.277 |
| TCP, deliberate QMP stop | yes | 0 | 0 | 0 | 1301.221 |
| TCP, passive FIONREAD | no | 3407 | 6193 | 2 | 1439.293 |
| TCP, direct write probe | no | 2382 | 4826 | 0 | 1402.563 |
| AF_UNIX, cold boot | yes | 0 | 0 | 0 | 1055.234 |
| AF_UNIX, repeat | yes | 0 | 0 | 0 | 1200.147 |

Qualification describes the offered load and measurement integrity. The deliberate-stop row is a calibration. Rows that failed qualification show the observed losses and exclude those runs from a filter comparison.

The AF_UNIX setup changes the socket family and moves QEMU from `socket` to `stream`. It avoids the tested TCP link, but the comparison cannot attribute the original stall to a single Windows or QEMU function. The public switch passed its TCP regressions and a native AF_UNIX forwarding check. The diagnostic images and raw captures stayed in the local lab. Both original profiles connected after the lab returned to ordinary DNAT, then all four VMs were shut down.

[Switch setup](lab-switch/README.md) · [Results JSON](results-v43.json)
