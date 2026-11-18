# V40: queue capacity and lost candidate notices

English | [Русский](validation-v40.ru.md)

The holding process now drains two NFQUEUEs through one socket, preserves the queue number with every packet ID, and retries failed local candidate notices. The runtime still has one C process and the same shared admission limits. Normal installers leave the experiment disabled.

The final ordinary trials delivered all 1,080,000 useful UDP packets and 300 ping replies. Three additional fault trials, including a forced notice failure and a 900-ms stop of C, delivered all 1,080,000 UDP packets and 300 replies. Ordinary maximum RTT was 1871.084 ms; the additional-fault maximum was 1875.280 ms. Late replies remain.

## Two different failure paths

On the tested Linux 6.12.117 kernel, one NFQUEUE held 65536 entries despite a requested maxlen of 131072. A loopback probe offered 90000 numbered UDP packets, continuously read their metadata, and withheld verdicts. A single queue delivered 65536 after release and dropped 24464. Two queues selected by `queue to numgen inc mod 2 offset 101` each held 45000 and delivered all 90000. The packet IDs overlapped 45000 times; verdicts must include the queue number.

A plain `queue num 101-102` range still put the test into one queue and dropped 24464. This kernel hashes IP addresses and protocol, without ports. NAT can therefore collapse the bridge traffic onto one queue. The retained rules explicitly alternate packets. The [kernel queue hash](https://github.com/gregkh/linux/blob/v6.12.117/include/net/netfilter/nf_queue.h), [queue expression](https://github.com/gregkh/linux/blob/v6.12.117/net/netfilter/nft_queue.c), [NFQUEUE implementation](https://github.com/gregkh/linux/blob/v6.12.117/net/netfilter/nfnetlink_queue.c) and [rhashtable implementation](https://github.com/gregkh/linux/blob/v6.12.117/lib/rhashtable.c) explain the observed distribution and ceiling. The [nftables manual](https://www.netfilter.org/projects/nftables/manpage.html) documents the runtime queue expression. Other kernels need their own capacity check.

The native-client control `pauseone1200` adds a 900-ms stop of C during A's crash recovery. It records 11932 kernel queue drops, 1416 missing useful UDP packets and 11 missing pings. With two queues, `pausedual1200` has no queue overflow but loses 2028 netlink deliveries, records one `ENOBUFS`, and misses 251 useful UDP packets and three pings. These are qualified failed workloads. Queue and netlink drops were not individually traced; their counters and missing-packet timing identify the bottlenecks without proving every drop's origin.

After those limits were addressed, `pausefinal1200b` exposed a separate lost-notice bug. All 368 missing useful UDP packets have authenticated ingress matches followed by C's hold and expiry records for moved port 42501. No query for that flow reaches A. C records a failed notice with code 11 about 961.749 ms after SIGKILL and never successfully sends that identity. Previously, a newly allocated flow made one notification attempt. A startup refresh could already have passed that slot, leaving the failed notice forgotten. The diagnostic code also used the failure record for socket-file validation, so code 11 alone does not distinguish every underlying syscall failure. The missing notification and lack of retry are directly observed.

## Retained changes and limits

Queues 101 and 102 each use maxlen 65536. One process and one netlink socket serve both; the global bounds stay at 131072 packets, 8192 held identities, 16384 packets per identity, 32 MiB of wire bytes and 2.6 seconds. Packet metadata remains 24 bytes. A queue ID uses existing padding. Both nftables examples and C must be updated together. A missing listener drops its selected packets; there is no queue bypass.

The copied packet portion falls from 128 to 80 bytes, covering the largest 60-byte IPv4 header, UDP and the 12-byte transport nonce. C stores packet IDs and metadata while the kernel keeps the complete encrypted skb. Conntrack attributes and netlink overhead are additional. Both copy sizes often consumed the same sampled 1280-byte allocation step, and a repeated 128-byte run also passed. The measurements do not establish a kernel-memory saving or a sufficient fix from copy reduction alone.

The shared netlink receive-buffer request rises from 16 to 20 MiB. Linux reports the corresponding limits as 32 and 40 MiB. This adds a bounded 8 MiB of reported socket allowance. It does not enlarge the holding deadline or authorize extra probes. The final buffer size is printed at startup.

A failed candidate notice now sets one pending bit in the live flow record, whose size remains 20 bytes. Once per 100 ms, C walks from a rotating cursor and attempts at most 64 pending notices, stopping that pass on a failed send. Repeated failures coalesce. Freeing the flow clears the bit; a later generation starts independently. Startup refresh failures use the same flag. These notices only request an exact-generation challenge. B must still authenticate a fresh post-query transport event, and A must recheck the mapping before installing a lease. Existing probe budgets and lease expiry are unchanged.

In `forcednotice1200`, a private diagnostic hook rejects one notice with `EAGAIN`. The pending-notice loop retries it after 100.404 ms; A receives the identity and the workload loses no useful UDP or ping. The hook is absent from public C.

## Native-client trials

Four local Debian 13 VMs have one vCPU and 1024 MiB each, without a CPU quota. Sixteen noise IPs offer 25000 packets/s for 70 seconds; useful UDP offers 6000/s for 60 seconds. The A-to-B link, including control TCP, has 150±30 ms delay per direction. Client-to-A is local. Three IP/NAT-port changes use requested 250-ms pauses. SIGKILL of A's helper on the first moved packet triggers systemd restart with RestartSec 200 ms. Every trial starts with a confirmed current-generation lease with over six seconds remaining.

Load trials use private diagnostic event records on A, B and C, plus an eight-second passive outer capture on the host switch. Exact public code is checked separately with both native profiles. Holding intervals use A's monotonic clock, outer-hop intervals use one host clock, and RTT uses the client capture clock. These measurements are not a throughput comparison of uninstrumented builds.

Trials marked `C pause` inject an additional 900-ms SIGSTOP of the holding process, followed by SIGCONT. The ordinary rows do not inject that pause. All rows below have qualified sender/noise accounting and zero switch/capture drops. Failures remain in the table.

Variant names: `baseline` has one queue, a 128-byte copy and a reported 32-MiB netlink limit; `dual` has two queues with those sizes; `dual80` uses an 80-byte copy. `final` adds the 40-MiB buffer before the notice fix. `retry` is the retained runtime; `forced` adds the private one-failure hook.

| Case | Variant / mode | UDP / bytes | Missing UDP / ping | Ping after 1 s | Max RTT ms |
|---|---|---|---:|---:|---:|
| pauseone1200 | baseline / C pause | up / 1200 | 1416 / 11 | 14 | 2166.530 |
| pausedual1200 | dual / C pause | up / 1200 | 251 / 3 | 26 | 1987.061 |
| pausecompact1200 | dual80 / C pause | up / 1200 | 0 / 0 | 17 | 2068.151 |
| pause128repeat | dual / C pause | up / 1200 | 0 / 0 | 23 | 2043.523 |
| pausefinal1200a | final / C pause | up / 1200 | 0 / 0 | 11 | 1959.794 |
| pausefinal1200b | final / C pause | up / 1200 | 368 / 2 | 7 | 1556.783 |
| finalup128 | retry / ordinary | up / 128 | 0 / 0 | 9 | 1871.084 |
| finalup1200b | retry / ordinary | up / 1200 | 0 / 0 | 11 | 1805.593 |
| finaldown1200b | retry / ordinary | down / 1200 | 0 / 0 | 8 | 1210.946 |
| forcednotice1200 | forced / C pause | up / 1200 | 0 / 0 | 9 | 1798.479 |
| pauseretry1200a | retry / C pause | up / 1200 | 0 / 0 | 15 | 1697.281 |
| pauseretry1200b | retry / C pause | up / 1200 | 0 / 0 | 12 | 1875.280 |

In the ordinary final cases, whole-VM CPU samples reach 84.62% and minimum MemAvailable is 482.4 MiB. With the additional faults, those values are 87.50% and 504.3 MiB. Final rows have no NFQUEUE overflow, user drops, ENOBUFS or C capacity drops. Cgroup memory readings are retained in the JSON; they exclude some kernel skb/socket memory, so they cannot establish total RAM consumption.

No final noise flow receives an authenticated lease. The two original native Linux profiles, keys and binaries are unchanged. The fixture uses Header Protection, S1-S4=12, H1-H4=1/2/3/4, Jc=0, random trailers and MTU 1280. Other parameter fixtures and physical GUI clients were not retested. Long holds and confirmation after a helper crash still produce late replies; this change provides no one-second roaming guarantee.

The first ordinary `finalup1200` attempt reused a guest directory from an older study. Append-mode logs contained two records, and the capture tool refused to replace existing sequence files. Their timestamps identify the old acquisition. That attempt is excluded without substituting old captures. The driver now creates stage-specific guest directories exclusively, and analysis checks capture timestamps against the sender and receiver intervals. Its repeat uses `finalup1200b`.

The first download `finaldown1200` has 10397 switch drops and 10397 missing useful UDP packets, concentrated in source seconds 1 through 4. Noise and endpoint-capture accounting pass, and NFQUEUE/netlink drop counters stay zero. The switch loss fails qualification; its repeat is `finaldown1200b`. The intermittent guest receive pause remains a lab limitation, also seen in v39.

The initial `baseup1200` acquisition has 3671 switch drops, including 2775 noise packets, and misses 896 useful UDP packets. It fails measurement qualification and is excluded from filter comparisons. Its raw result is retained. The old 122-packet incident remains unproved at the individual-packet level, as recorded in [v39](validation-v39.md).

## Checks and reproduction

All 52 Python tests pass on Windows and Linux. Exact public C passes optimized and ASAN/UBSAN self-tests, including overlapping queue IDs, shared limits, the 80-byte maximum-header case, failed-notice backoff, a 64-attempt pass and expiry without stale retries. Both unchanged native profiles pass through the exact public agent and C binary without diagnostic wrappers.

[The queue probe](research/v40-queue-probe.c) includes the public verdict builder. Compile with assertions enabled and libnetfilter_queue inside the disposable entry VM. It requires hostname `kit-entry`, root, a private network namespace distinct from PID 1's namespace, and only loopback. In that namespace, place an OUTPUT rule for UDP 127.0.0.1:5353 using the selector under test. Invoke `--vm-test one` with `queue num 101`; invoke `--vm-test two` with the explicit alternating selector. The `wrong` control sends every verdict to queue 101: half of 512 packets stay held on 102 and 256 missing-ID errors are counted. The `missing` control binds only 101 while the rule alternates: half are dropped. Using a plain range with the `two` probe intentionally returns failure on this kernel. Destroy the namespace after each run, including failed runs. This checks kernel capacity, verdict routing and fail-closed behaviour; it does not test client authentication or VPN throughput.

[results-v40.json](results-v40.json) retains case metrics, raw-file hashes, source hashes and cleanup receipts. [The retained patch](research/v40-retained.patch) reconstructs C, both rule examples and the probe from `48d5a5b5c585ce433d57bca0ea32944c9661a7f5`. Patch application and byte reconstruction pass. Raw captures, diagnostic session keys and disks stay local and ignored. New prose was reviewed with Humanizer. The unrelated repository suite and unchanged switch regressions were not rerun in this stage.

## Cleanup and remaining work

Ordinary DNAT and stock B are restored, and both original profiles pass. Experimental hooks, queues and the routed bridge are removed. All four VMs and the owned switch/seed processes are stopped; lab ports bind exclusively and the backing image hash is unchanged. Previous reports and personal routing JSON are unchanged. Production servers, the user's VPN, host network settings, commits and GitHub are unchanged. The receipts describe the end of this local study.

Shared-NAT pressure, excessive untrusted candidate counts, spoofed leased tuples, longer outages and link saturation remain limits. Holding retains attack traffic and kernel skb overhead beyond C's byte counter. A whole-VM memory budget still needs monitoring. There is no new IPv6, DPI or long-soak validation. Strict filtering still removes I/J camouflage between A and B.
