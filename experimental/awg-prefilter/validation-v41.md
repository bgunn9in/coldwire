# V41: entry maintenance deadline and switch output stalls

English | [Русский](validation-v41.ru.md)

The entry helper now bounds its socket wait by the time left before scheduled maintenance. The normal interval stays at 100 ms, and the wait still has a 50 ms cap. The previous loop could sleep through a deadline even when maintenance was already due. The regression checks a due deadline, the 50 ms cap, and a deadline 30 ms away. The exit loop keeps its existing wait.

## What the traces show

In v40's worst ordinary upload ping, the client measured 1871 ms RTT and C held the request for 1480 ms. In the same trial, measured from SIGKILL, A started at 388 ms, finished TCP at 740 ms, and finished TLS at 1118 ms. The first moved flow's proof was accepted at about 1564 ms. Those intervals include process restart and network round trips, so changing a local wait can affect only part of them.

Enabling TCP_NODELAY before the TLS handshake was tested separately. In an alternating control-only series with eight measured handshakes per setting, the median time to connect, authenticate and exchange one byte was 978 ms with the existing setting and 946 ms with the early setting. Their ranges overlapped. The full load trial reached 2055 ms with early TCP_NODELAY and 1840 ms with the existing setting. Early TCP_NODELAY stays out of the prototype. [OpenSSL's handshake notes](https://docs.openssl.org/3.6/man3/SSL_connect/)

## Load trials

Four isolated Debian 13 VMs used one vCPU and 1024 MiB each without a CPU cap. The lab offered 25,000 noise packets/s from 16 IPs and 6,000 useful UDP packets/s, with 150 ± 30 ms delay in each direction between A and B. The client changed IP and NAT port three times. A's helper was killed at the first move and restarted by systemd. The client profiles, keys and binaries were the same throughout.

| Trial | Direction and UDP payload | Missing UDP / ping | Ping after 1 s | Max RTT, ms |
|---|---|---:|---:|---:|
| Old timer | upload, 128 | 0 / 0 | 16 | 1882.461 |
| Fixed timer, repeat | download, 1200 | 0 / 0 | 10 | 1248.090 |
| Fixed timer | upload, 128 | 0 / 0 | 16 | 1989.660 |
| TCP_NODELAY after TLS | upload, 128 | 0 / 0 | 12 | 1840.223 |
| TCP_NODELAY before TLS | upload, 128 | 0 / 0 | 14 | 2055.347 |

Both qualified 128-byte timer runs had 16 replies after one second. The comparison did not show faster recovery.

## Switch diagnostics

The Windows switch now counts output ring drops per connection and records the longest gap between successful writes while data is queued. The previous queue age measured the entire interval during which the ring stayed nonempty, including successful writes. The write gap measures host-side socket progress. It cannot identify whether a guest RX stall, QEMU scheduling or another downstream condition caused backpressure.

In the first download run the output ring toward A dropped 9284 frames and the ring toward the client dropped 4238. The longest write gap toward the client rose from 0.398 to 1229.744 ms. Guest NIC drop counters stayed at zero. B’s source capture missed 30 packets, so this run is excluded from prototype latency and loss comparisons. The C self-test verifies per-connection overflow accounting and the write-gap calculation. In a separate slow-reader loopback check, the switch socket accepted the test stream without filling the ring.

All 53 Python tests passed on Windows and Linux. Both original clients connected with the public agent source. The lab returned to plain DNAT with stock B before the VMs and their helper processes were stopped.

[Machine-readable results](results-v41.json) include NIC samples, queue counters and stage timings. [Code patch](research/v41-retained.patch)
