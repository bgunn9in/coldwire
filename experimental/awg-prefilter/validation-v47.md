# V47. What delayed BQL acquisition on Windows

English | [Русский](validation-v47.ru.md)

The two AF_UNIX runs used four Debian 13 VMs on QEMU 11.1.3/WHPX. Each VM had one vCPU and 1024 MiB with no CPU quota. Client profile and binary hashes matched. The offered workload was 25,000 background packets/s from 16 addresses and 6,000 useful UDP packets/s at a nominal RTT of 300 ms with jitter.

ETW recorded context switches and transitions to the ready state. QEMU marked the call to `AcquireSRWLockExclusive` and recorded who held the BQL. The traces were aligned on a 10 MHz QPC clock. QEMU logged its main thread ID and QMP identified the vCPU threads. In a control with a known SRW lock holder, the acquisition lasted 350.385 ms. The acquiring thread spent 350.340 ms waiting and 0.014 ms ready. [Windows scheduler event types](https://learn.microsoft.com/en-us/windows/win32/etw/thread-v2)

## Lock contention at startup

The first ETL hit its 512 MiB limit. It retained startup and 3.95 seconds of load. All four intervals below fit inside the trace. The vCPU held the BQL after acquiring it in `prepare_mmio_access()` at `system/physmem.c:3193`.

| VM | BQL acquisition, ms | Main waiting, ms | Main ready, ms | vCPU running with BQL, ms | vCPU waiting with BQL, ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| A | 22.475 | 22.460 | 0.007 | 22.463 | 0.000 |
| B | 12.255 | 12.238 | 0.007 | 0.024 | 12.210 |
| Client | 11.276 | 11.251 | 0.018 | 11.254 | 0.000 |
| Generator | 48.938 | 48.921 | 0.007 | 0.029 | 48.885 |

On A and the client, the holder ran almost the entire time. On B and the generator, the holder spent most of the interval waiting while it held the BQL. The trace identifies the call site and thread state. The MMIO device and the underlying Windows wait object remain unknown.

## Full workload window

The second trace started after guest setup and retained all 69.96 seconds of load. It recorded 14,744,118 context switches and 8,103,794 ready-thread events. ETW reported zero lost events and buffers. No main thread acquisition of at least 5 ms was recorded under load. Both runs delivered all 1,750,000 background frames to A with zero switch drops. In the second run with tracing enabled, the application missed 7,444 useful UDP packets and 44 ping replies.

The 14.4-second shared pause from v45 did not recur. It occurred before scheduler tracing was enabled. These startup results leave the cause of that historical pause open.

[Lab setup and trace commands](lab-switch/README.md#bql-and-windows-scheduler-tracing) · [Results JSON](results-v47.json)
