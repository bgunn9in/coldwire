# V46. Switch queue overflow and delays when writing lab artifacts

English | [Русский](validation-v46.ru.md)

The five local runs used the v45 QEMU configuration. Each Debian 13 VM had one vCPU and 1024 MiB without a CPU quota. The same profiles carried 6,000 useful UDP packets/s at a nominal 300 ms RTT with jitter. The background target stayed at 25,000 packets/s from 16 addresses. Four runs alternated 4,096- and 512-packet bursts. A final run kept 4,096-packet bursts and moved the switch's JSON, pcap and log to a separate physical disk.

## The earlier 14.4-second pause

In v45 the Windows poll took 3.9 ms on A and about 3.0 ms on B and the generator. Between poll return and reacquiring the QEMU Big Lock (BQL), those processes took 8,448.9, 9,210.2 and 8,683.7 ms respectively. Their acquisition timestamps landed within 12.5 µs. The duration includes time the host may have spent scheduling the threads. QEMU record/replay was off. The available Windows event logs give no cause for the common interruption. It did not recur in v46.

## The 1,040 switch drops

The v45 repeat filled the 4 MiB queue toward A to 4,194,060 bytes. A counted 984 fewer background packets than the switch received. The old records lack per-frame loss attribution for the remaining difference. The switch now records separate counts for background frames and other frames and logs loss intervals, time in polling and forwarding, and slow JSON writes.

| Run | Switch files | Burst | Max. queued write gap to A, ms | Longest stats write under load, ms | Switch drops | Noise received at A | Missing UDP | Missing ping |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| q46-wide-a | VM disk | 4096 | 468.0 | 467.0 | 0 | 1750000 | 3653 | 10 |
| q46-paced-a | VM disk | 512 | 253.4 | 252.8 | 0 | 1750000 | 8002 | 46 |
| q46-paced-b | VM disk | 512 | 57.8 | 220.8 | 0 | 1750000 | 0 | 15 |
| q46-wide-b | VM disk | 4096 | 113.0 | 468.5 | 0 | 1750000 | 120 | 3 |
| q46-wide-cdisk | separate disk | 4096 | 100.4 | <20 | 0 | 1750000 | 7437 | 54 |

The output ring dropped no frames in the five runs. Smaller bursts gave no consistent advantage in peak queue occupancy. With a 512-packet burst setting, the switch still received up to 10,373 background frames in 100 ms as the sender caught up after delays.

On the VM disk, synchronous JSON writes took up to 468.5 ms under load and 3,036.2 ms before load. The independent Windows clock observer and both QEMU receiver observers continued sampling during the largest statistics-write delay under load. A 440.5 ms interval in the forwarding loop also fell inside the host pcap window. That measurement covered the entire forwarding path.

With the switch files on the separate disk, all statistics writes stayed below the 20 ms logging threshold and the largest queued write gap to A was 100.4 ms. A counted all 1,750,000 background packets. Packet captures dropped 2,505 packets at B and 3,721 at the client, so this control cannot compare filter behavior. After collection, QEMU A exceeded the shutdown wait and the launcher stopped its remaining lab processes. The historical overflow trigger was not reproduced in this series. [Windows active-time counter](https://learn.microsoft.com/en-us/windows/win32/api/realtimeapiset/nf-realtimeapiset-queryunbiasedinterrupttime)

[Lab switch](lab-switch/README.md) · [Results JSON](results-v46.json)
