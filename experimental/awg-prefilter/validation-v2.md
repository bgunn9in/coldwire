# Prefilter follow-up, 11 November 2026

English | [Русский](validation-v2.ru.md)

The revised filter copies 212 bytes from NFQUEUE and has a separate optional
kernel rate guard.
The [original report](validation.md) remains the record of the earlier build.
All measurements and source/binary hashes for this run are in
[results-v2.json](results-v2.json).

Four local Debian 13.7 VMs each had 1 vCPU and 1024 MiB RAM. They used
separate copy-on-write disks over the stopped lab images, the same pinned
AWG core and the localhost-only learning switch. The entry ran Linux
6.12.115, OpenSSL 3.5.7, libnetfilter_queue 1.0.5 and nftables 1.1.3.
All traffic tests stayed between the VMs.

## Changes checked

The filter copies at most 212 bytes, verifies the original packet length
from `NFQA_CAP_LEN` and decrypts handshakes through MAC1. Kernel GSO
normalization remains enabled. A live test exposed an error handling the
last netlink message without alignment padding. That error was fixed before
the measurements below. Live ping tests then covered eight payload sizes
for each of two native clients, including odd packet lengths.

The separate kernel guard limits each source-IP/UDP-port tuple, then the
aggregate rate. Its set holds 4096 entries with a five-second idle timeout.
The example uses 35,000 packets/s per tuple and 50,000 packets/s aggregate,
with bursts of 3500 and 5000 packets. These rates permit the measured clean
traffic, including two concurrent clients. They remain lab settings and do
not establish a safe NFQUEUE admission rate for another host.

## Clean TCP

Each row is the median of three runs per direction. Each run measured eight
seconds after a one-second warmup. Mode order rotated between repetitions.
`Filter` uses the new binary alone. `Full copy` rebuilds the original source
with the same compiler. Profiling was disabled in every throughput run.

| Mode | Upload Mbit/s | Download Mbit/s | Entry CPU upload | Entry CPU download |
|---|---:|---:|---:|---:|
| DNAT | 146.00 | 133.17 | 78.65% | 80.99% |
| Kernel guard | 152.94 | 131.20 | 84.32% | 79.93% |
| Filter | 149.92 | 143.02 | 31.86% | 54.41% |
| Kernel guard + filter | 149.95 | 133.02 | 31.90% | 49.89% |
| Full copy | 149.68 | 139.73 | 29.89% | 48.89% |

Filter RSS was about 6.3 MiB, excluding kernel socket, queue and set memory.
The smaller copy produced no consistent CPU or throughput improvement over
the original filter. The kernel retains the full encrypted packet while it
waits for a verdict.

Guest CPU accounting differs sharply from the earlier lab. A separate
upload check recorded 720 of 887 entry CPU ticks in softirq for DNAT, with
zero steal ticks. This establishes where that guest accounted the time.
The cause of the difference from the earlier run remains unresolved. These
figures describe this VM setup and should not be used to rank VPS CPU costs.

## Controlled noise

An independent VM sent random 256-byte UDP payloads while TCP upload was
active. Every sender run achieved its requested rate within 1%. Values are
medians of two runs, with the mode order reversed in the second repetition.

| Achieved noise packets/s | DNAT Mbit/s | Kernel guard Mbit/s | Guard + filter Mbit/s |
|---|---:|---:|---:|
| 5000 | 102.98 | 100.33 | 137.70 |
| 10000 | 66.40 | 68.16 | 124.72 |

The switch recorded zero drops. At 5000 packets/s the combined mode had no
queue drops. At 10,000 packets/s it recorded 1067 and 1137 queue drops, with
zero sampled netlink user drops. Useful traffic recovered after every case.
The example's high rate limits do not prevent those queue losses. Adding
the filter increased useful throughput in these samples.

Earlier attempts requested 30,000 and 60,000 packets/s, but the sender
achieved roughly 16,000–22,000 and differed between modes. Those raw results
are retained as saturation observations, outside the controlled comparison.

## Profiling

An instrumented build measured thread CPU time in separate upload/download
runs. Upload copied 27,441,843 of 174,987,051 original packet bytes, a reduction
of 84.3%. Download copied 7,002,392 of 7,038,215 bytes because most checked
inbound packets were small TCP acknowledgements.

During upload, receiving netlink messages consumed 0.334 s, inspection
0.543 s and verdict submission 1.390 s of measured thread CPU time. Header
decoding consumed 0.300 s within inspection. No handshake occurred during
that sample. Clock calls add overhead, and receive time includes syscall
and dequeue work. The measurements point to verdict submission as the next
place to investigate. Any batching must still validate each datagram before
an accept verdict covers it. [NFQUEUE documentation](https://www.netfilter.org/projects/libnetfilter_queue/doxygen/html/group__Queue.html).

## Recovery and security checks

- Two fresh native clients worked behind a shared NAT in all three main
  modes. IP/port roaming and reassignment of the same outer tuple to the
  second client also worked.
- Two simultaneous TCP clients produced zero guard drops in both guarded
  modes. A separate functional test temporarily lowered the guard rates and
  offered 6000 noise packets. Counters covering noise and client traffic
  recorded 1051 admissions and 4953 drops. The legitimate client still worked.
- The flow set reached its 4096-entry bound. A new client tuple was dropped
  while it was full and worked after idle entries expired.
- Wrong HPK and an unregistered client key could not use the VPN. All 100
  packets spoofing the backend address/port in the original direction were
  checked and dropped.
- A sender without the key file sent 100 captured-prefix packets with altered
  payload. The filter admitted them. Flow accounting provides no client
  identity guarantee, and the implementation adds no admission cache.
- Killing the queue process stopped filtered traffic. Removing only the two
  experimental tables restored DNAT. The ordinary relay rules stayed equal.

A startup capture counted six unrecognized packets on the client-to-entry
link in each mode. DNAT forwarded all six. The combined mode forwarded none
of them. Forwarded packet payloads matched their incoming payloads byte for
byte. The strict I1/Jc policy therefore continues changing the entry-to-exit
pattern. DPI resistance and physical GUI clients remain untested.

All 16 offline tests passed in optimized, ASan/UBSan and profiling builds.
The project's 50 Python tests passed without skips in its existing virtual
environment. Both exception-list snapshots reproduced byte for byte without
additional protected addresses. All lab guests and helpers were stopped.
