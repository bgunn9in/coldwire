# V39: restart latency and holding expiry

English | [Русский](validation-v39.ru.md)

The retained early-probe variant delivered all 1,440,000 useful UDP packets and 400 ping replies in four final trials. Of those replies, 37 arrived after one second; maximum RTT was 1736.487 ms. A same-cohort ACK-only control reached 2052.289 ms. These are separate jittered trials, not a guarantee of the improvement on other networks. Normal installers still leave the prototype disabled.

## Why the delay occurs

A helper crash puts several waits in series: systemd restart and Python startup, TCP establishment, mutual TLS, B's acknowledgement of the nonce, a held-packet probe, and the authenticated proof returning to A. Rule installation, release and packet travel follow. The confirmed-start control `tap25b` reproduced a 2231.314-ms ping without queue, switch or capture loss. Its worst request spent 1862.354 ms held in C.

With the retained 2.6-second holding setting, `normalbase26` reached 2052.289 ms; 1680.154 ms of its worst request was holding time. A queued the nonce for port 42501 at 1109.12 ms after SIGKILL and accepted its proof at 1797.18 ms. In `earlyup1200a`, those times were 1023.04 and 1484.04 ms. Thus the observed query-to-proof interval fell from 688.06 to 461.00 ms. Independent path jitter and TLS timing also differed. The worst ping's holding time fell to 1348.270 ms in that trial.

A passive eight-second capture on the Windows switch replaces full outer capture inside A. Only low-rate control TCP is captured in the guest. Matching authenticated outer ciphertext to inner sequence numbers and C's nonce records separates holding expiry from replay rejection. Diagnostic session keys remain in a root-only directory on the disposable exit VM; they are absent from the repository. Holding durations use A's monotonic clock, outer hop intervals use one host clock, and RTT uses the client's capture clock.

## The earlier 122 UDP packets

The preserved v38 `queueup1200` source capture contains 122 missing packets, spread across sequences 154526 through 154656. Their timestamps fall 120.404 to 142.259 ms after the first NAT change began, in the first moved mapping, port 42501. That port's proof reached A 2467.189 ms after SIGKILL. Its actual release still required rule installation and delivery of C's grant snapshot.

A new control deliberately increases only A's restart pause from 200 to 1200 ms and uses the older 2.5-second holding limit. `edgebase25` loses 92 useful UDP packets and one ping. Every one of those 92 packets has an authenticated ingress match followed by C's hold and expiry records, with no forwarding copy or replay-rejection record. The old-flow proof arrives at about 2584 ms and rule installation ends at 2614 ms. Queue, switch and capture drop counters stay zero. This directly demonstrates expiry during the confirmation handoff.

The original 122 lack per-packet C records and complete outer captures, so their exact drop stage remains unproved. Their timing supports the expiry explanation; the new 92-packet reproduction does not retroactively identify those old packets. The retained holding limit stays at 2.6 seconds.

## Retained change

A tracks which pending nonce requests have drained from its TLS output buffer. On a subsequent maintenance pass it may request one early held packet with root-only `CWT1`. C limits these probes to 32/s with burst 32 within the existing aggregate 64/s, burst-64 budget. A can request one `CWS1` fallback after B acknowledges the nonce. Later unwritten queries do not block an earlier written query.

A probe grants no lease. B must still authenticate a fresh transport event after receiving that nonce query; its replay and source checks remain unchanged. A rechecks the exact current conntrack generation. Unit tests reject pre-query events, blocked or partial TLS writes, expired nonces and invalid local requests. C's self-test verifies that mixed early and normal probes cannot exceed the aggregate budget.

An immediate-after-write variant is rejected. UDP can arrive before the TLS query under jitter, requiring the ACK fallback. With the injected 1200-ms restart pause, `edgeearly25` lost 878 UDP packets: 706 have C expiry records; 172 have no C record and match 172 kernel queue drops. It does not establish an improvement over the control. The retained variant keeps the existing maintenance cadence. The v34 experiment remains rejected; v39 tracks written requests individually and tests a separate early-probe sub-budget in this crash-recovery cohort.

## Final trials

All trials use four local Debian 13 VMs with one vCPU and 1024 MiB each, without a CPU quota. Sixteen noise IPs offer 25000 packets/s for 70 seconds; useful UDP offers 6000/s for 60 seconds. The link between A and B, including control TCP, has 150±30 ms delay per direction. Client-to-A is local. Three changes of IP and NAT port have requested 250-ms pauses; SIGKILL on the first moved packet triggers systemd restart. Each trial starts with a confirmed current-generation client lease with more than six seconds remaining.

| Case | Direction / UDP bytes | Missing UDP / ping | Ping after 1 s | Max RTT ms |
|---|---|---:|---:|---:|
| normalbase26 | up / 1200 | 0 / 0 | 12 | 2052.289 |
| earlyup128 | up / 128 | 0 / 0 | 11 | 1455.104 |
| earlyup1200a | up / 1200 | 0 / 0 | 8 | 1728.908 |
| earlyup1200b | up / 1200 | 0 / 0 | 11 | 1736.487 |
| earlydown1200b | down / 1200 | 0 / 0 | 7 | 1224.153 |

Every final row has exact offered-noise accounting, zero switch/capture drops, zero NFQUEUE overflow/user drops and zero C capacity drops. No noise flow receives an authenticated lease. Final VM CPU samples reach 92.31%; minimum MemAvailable is 465.6 MiB. These are observed samples, not a capacity guarantee. Client files, keys and binaries stay unchanged. The fixture is the same two native Linux clients as v38: Header Protection, S1-S4=12, H1-H4=1/2/3/4, Jc=0, random trailers, MTU 1280. GUI clients and other wire-parameter fixtures were not measured in this cohort.

## Kernel queue limit and excluded measurements

The failed immediate-probe control also exposed a kernel bound. Kernel 6.12.117 logs `hash insert failed: -7`; NFQUEUE uses at most 32768 hash buckets and rhashtable caps entries at twice that value. Thus one queue can hold at most 65536 entries despite a requested maxlen of 131072. This is separate from C's userspace capacity and is still a loss risk during larger backlogs. See the [NFQUEUE implementation](https://github.com/gregkh/linux/blob/v6.12.117/net/netfilter/nfnetlink_queue.c) and [rhashtable initialization](https://github.com/gregkh/linux/blob/v6.12.117/lib/rhashtable.c). The 172 individual kernel drops were not traced; their attribution uses matching counts and timing.

Full outer capture inside A perturbed `trace26a`, which failed measurement qualification. `tap26a` also had switch/NFQUEUE drops and lacked the confirmed-start check. `tap25a` failed during setup before load. The first final download acquisition, `earlydown1200`, lost 7099 switch copies and 5489 useful UDP packets; it is excluded from filter comparisons. Its repeat passed. This intermittent guest receive pause remains a lab limitation. Failed and excluded cases remain in the JSON.

## Checks and cleanup

All 52 Python tests pass on Windows and Linux. The final C source passes its optimized self-test and ASAN/UBSAN. Tests cover write ordering, session resets, a later unwritten query, post-query freshness and mixed probe budgets. The native switch passes its pure and localhost socket regressions. Both unchanged client profiles also pass with the exact public agent and C binary, without diagnostic wrappers. The full unrelated repository suite was not rerun.

[results-v39.json](results-v39.json) records cases, hashes and cleanup. [The retained patch](research/v39-retained.patch) reconstructs the runtime and tests from `65fbd03e43d09985613d480540b4c692c2ee3675`; application and byte reconstruction passed. Raw captures, diagnostics, lab keys and disks stay local and ignored. Documentation was reviewed with Humanizer.

The cleanup and Git-state records describe the end of the local study, before publication.

Ordinary DNAT and stock B were restored and both original profiles passed. Experimental hooks, queues and the routed bridge were removed; stale ARP entries for A were expired after its MAC changed. All four VMs and owned switch/seed processes are stopped, localhost lab ports bind successfully, and the backing image SHA512 is unchanged. Previous reports and personal routing JSON are unchanged. Production servers, the user's VPN, host network settings, Git commits and GitHub were not changed.

Longer outages, shared-NAT pressure, spoofed leased tuples and link saturation can still cause loss. The 65536-entry kernel ceiling needs a separate queue-layout change for larger backlogs. The experiment provides no one-second roaming guarantee, IPv6 support, GUI-client validation, DPI result or long-soak result. Strict filtering still removes I/J camouflage between A and B.
