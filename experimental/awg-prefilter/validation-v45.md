# V45. Receiver-side socket observations and a shared lab interruption

English | [Русский](validation-v45.ru.md)

The v44 setup was repeated using the [QEMU stream observer patch](lab-switch/qemu-win32-stream-observer.patch). A separate thread measured `FIONREAD` and recorded the last main-loop heartbeat and Virtio read-watch state. During a long read gap it sampled about every 50 ms. The first two passes instrumented A. The remaining passes also instrumented the client VM. VM resources, target workload and client profiles matched v44.

| Run | Max. queued write gap, ms | Switch drops | Noise received at A | Missing UDP | Missing ping |
| --- | --- | --- | --- | --- | --- |
| rx-tcp-a | 1215.2 | 4287 | 1750000 | 8772 | 0 |
| rx-tcp-b | 967.5 | 23347 | 1731391 | 4737 | 0 |
| rx-tcp-c | 336.9 | 2678 | 1747495 | 173 | 0 |
| rx-unix-control | 14373.5 | 202712 | — | — | — |
| rx-unix-repeat | 73.2 | 1040 | 1749016 | 1132 | 21 |

## Open-window TCP stall

In `rx-tcp-b` the switch's queue to A went at least 869.7 ms without a successful write in the sampled interval. Nine sender samples showed an open 16,776,960-byte window, and retransmissions increased by 658,956 bytes. All 15 receiver samples reported zero bytes available. The read watch stayed armed and the main-loop heartbeat advanced about 756 ms. Two successful-read gaps were about 479 ms each. This places the delay before bytes became available to QEMU. A shorter open-window episode with the same receiver signal appeared in `rx-tcp-c`. The loss in `rx-tcp-a` was on the client output, where the receiver thread was not enabled yet.

## AF_UNIX control

During the first AF_UNIX control, reads at A, B and the client stopped for a common interval of 14.374 seconds. The switch received zero background frames in all 142 fully overlapping 100 ms bins. Two receiver threads went about 14.339 seconds between samples. The generator's management SSH connection also timed out, leaving the run incomplete. These records locate a shared lab interruption. They do not identify its source.

In the repeat, a separate Windows clock observer recorded no sampling gap over 250 ms during the load. The switch's queue to A still overflowed and dropped 1,040 frames. Its maximum queued write gap was 73.2 ms. The open-window trace does not establish the trigger for either the zero-window event in v44 or the 4.77-second event in v42.

[Lab switch](lab-switch/README.md) · [Results JSON](results-v45.json)
