# V49. Buffering COM1 and retesting the 14.4-second pause

English | [Русский](validation-v49.ru.md)

The lab switched COM1 from a file to QEMU's 1 MiB memory ring. The serial handler copies bytes into memory. The launcher drains the ring over local QMP after the load and ETW capture end. It recovered 59,861 to 61,377 bytes from each of the four VMs.

The completed runs used the same QEMU 11.1.3/WHPX launch arguments apart from COM1. Each VM had one vCPU and 1024 MiB with no CPU quota. Both runs used AF_UNIX, 25,000 background packets/s from 16 addresses and 6,000 useful UDP packets/s at a nominal RTT of 300 ms with jitter. The client profiles and AWG binary hashes matched.

| Measurement | COM1 file | COM1 ring |
| --- | ---: | ---: |
| Background sender rate, packets/s | 24,999.954 | 24,999.959 |
| Background packets at the switch | 1,750,000 | 1,750,000 |
| Background packets at A | 1,740,805 | 1,750,000 |
| Frames dropped by the switch | 11,133 | 0 |
| Longest gap between switch writes with a nonempty queue | 589.44 ms | 543.08 ms |
| Longest shared read gap at A, B and the client | 600.01 ms | 545.92 ms |
| Longest run of empty 100 ms switch bins | 7 | 5 |
| Useful UDP packets missing at the application out of 360,000 | 6,070 | 0 |
| Missing ICMP replies out of 100 | 0 | 0 |
| COM1 holds of at least 1 ms across boot and load | 21, up to 373.00 ms | 0 |
| Longest main-thread BQL wait under load | 241.74 ms | 25.67 ms |
| Longest sample gap on the independent Windows clock observer | 585.57 ms | 52.12 ms |

Both ETW sessions captured the full load window with zero reported lost events. The 72.92 s and 72.16 s traces contained 9,451,702 and 11,791,110 context switches, respectively. The shared read gap is the overlap of three QEMU receive gaps.

All recorded COM1 holds were during startup in the file run. Under load in that run, the longest vCPU hold began in the WHPX interrupt handler. The vCPU spent 241.56 ms waiting. The kernel stack includes NTFS, and the trace lacked the user frames needed to identify the exact operation.

The 14.4 s pause did not recur. The file run's UDP capture at B lost 964 records. The table uses the application counters for UDP delivery. One pair of runs leaves both the cause of the historical pause and the effect of COM1 buffering on packet loss open.

An early file run timed out on SSH. An early ring run reached NFQUEUE before the listeners were ready. The two measured runs waited for the listeners. After the ring measurement, VM A exceeded the 20 s shutdown wait. The launcher stopped its process and verified that all lab ports were free.

[COM1 setup and log retrieval](lab-switch/README.md#buffer-com1-on-the-host)
