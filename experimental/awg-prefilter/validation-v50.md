# V50. Six alternating COM1 file and ring-buffer runs

English | [Русский](validation-v50.ru.md)

The 14.4 s pause did not recur. The longest gap shared by A, B and the client was 86.36 ms. All 1,750,000 background packets reached A in each run, and the switch dropped no frames. No two consecutive 100 ms bins at the switch were empty during any load window.

| Run | COM1 | Missing useful UDP packets out of 360,000 | Missing ping replies out of 100 | Longest shared read gap |
| --- | --- | ---: | ---: | ---: |
| 1 | File | 1,038 | 17 | 61.31 ms |
| 2 | ringbuf | 1,027 | 9 | 79.24 ms |
| 3 | File | 1,907 | 8 | 18.76 ms |
| 4 | ringbuf | 2,458 | 29 | 86.36 ms |
| 5 | File | 8,278 | 53 | 83.20 ms |
| 6 | ringbuf | 0 | 0 | 65.14 ms |

Median UDP losses were 1,907 per file run and 1,027 per ring-buffer run. The ring buffer lost more in the second pair. The three pairs show no consistent effect on delivery. UDP losses come from receiver counters. The captures on both ends reported zero drops.

## COM1 and the BQL

Across startup and load, file-backed COM1 held the BQL for at least 1 ms on 26 occasions. One occurred under load in run 5. The entry VM's vCPU held the BQL for 39.65 ms while writing to port `0x3F8` and spent 39.29 ms waiting. The ETW kernel stack includes NTFS. It lacks user-mode frames for that switch. QEMU's main thread waited 39.30 ms for the BQL, overlapping the vCPU hold by 39.28 ms.

The three ring-buffer runs recorded no COM1 holds of at least 1 ms. All four serial logs were recovered over QMP after each ring-buffer run. The result confirms that buffering removes the synchronous file write from the COM1 handler. The cause of the historical pause remains open.

## Test conditions

Four local QEMU 11.1.3/WHPX VMs used AF_UNIX and had 1 vCPU and 1024 MiB each, with no CPU quota. The launch arguments matched apart from COM1. Both client profiles and the AWG binary matched their saved hashes throughout the series.

Each run offered 1,750,000 background packets from 16 addresses over 70 s. The measured generator rate ranged from 24,999.94 to 24,999.96 packets/s. Useful UDP ran at 6,000 packets/s, with a nominal RTT of 300 ms and jitter.

The six ETW traces covered the full load windows. They lasted 71.89 to 72.10 s and reported zero lost events. The shared read gap is the overlap of gaps in three QEMU receive logs. The independent Windows clock observer had a maximum sample gap of 74.79 ms. After the series, the lab stopped its VM processes and trace sessions and verified that its 19 local ports were free.

[COM1 setup and log retrieval](lab-switch/README.md#buffer-com1-on-the-host)
