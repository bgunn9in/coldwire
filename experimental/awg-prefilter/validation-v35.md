# V35: where roaming latency comes from

English | [Русский](validation-v35.ru.md)

The 1302.170-ms response in v34 was measured across three consecutive IP/NAT-port changes. The client had already waited 823.495 ms by the end of the last change; the reply arrived 478.675 ms later. That value includes the moves and network transit. It is not a 1.3-second processing stall in the filter.

V35 keeps one small change: B's existing maintenance worker checks armed return recovery every 10 ms instead of 100 ms. The per-peer and global replay spacing remains 250 ms. This reduces timer granularity, but total roaming RTT did not improve in every pair. The largest candidate RTT in this study was 1383.822 ms. There is still no one-second guarantee.

## Measurements

Four isolated local Debian 13 VMs ran under QEMU/WHPX, each with one vCPU and 1024 MiB RAM, without a CPU limit. QMP checks confirmed those resources. Each qualified trial sent noise at 25,000 packets/s from 16 IPs for 70 seconds and useful UDP at 6000 packets/s. Nominal RTT was 300 ms, with normal jitter of 30 ms in each direction, on VPN and control paths.

Download payloads were 1200 bytes with 64 noise flows. Upload payloads were 128 bytes with 8192 noise flows and a forced SNAT-port collision with a second native client. Both clients kept their original binaries, profiles, keys and listen ports. Changes affected only the disposable NAT gateway. The single-move fixture uses the harness's zero-gap mode; its raw specification still carries a three-move maximum, while the recorded event list contains exactly one move.

Every pair below uses the same configuration. Jitter and host scheduling are independent between runs, so differences in maximum RTT do not isolate the timer's effect. The last three columns list control / candidate, with maintenance periods of 100 / 10 ms.

| Scenario | All UDP, control / candidate | Maximum RTT, ms | Ping > 1 s |
|---|---:|---:|---:|
| DL, 3 moves, 250 ms, no B timing | 362,022 / 362,244 | 1445.437 / 1219.631 | 5 / 4 |
| DL, 3 moves, 250 ms, timing 1 | 361,904 / 362,307 | 1354.315 / 1322.096 | 6 / 6 |
| DL, 3 moves, 250 ms, timing 2 | 362,131 / 362,055 | 1355.922 / 1383.822 | 10 / 8 |
| DL, 3 moves, 100 ms, timing | 362,118 / 361,846 | 1068.384 / 963.147 | 1 / 0 |
| UL, 3 moves, 100 ms, SNAT collision | 360,001 / 360,003 | 770.897 / 843.115 | 0 / 0 |
| DL, one move, timing | 362,018 / 361,492 | 761.719 / 687.638 | 0 / 0 |

All 4,340,141 unique useful UDP packets and all 1200 ping replies arrived in the 12 qualified trials. Forty ping replies exceeded one second: 22 in controls and 18 in candidates. Final unique sequence sets, complete captures and source rates determine delivery. Iperf's provisional loss counts include packets that arrived later.

Qualified trials had no switch, WAN, capture or NFQUEUE drops. Noise received no authenticated leases and never entered the trusted path. The entry's peak CPU sample was 62.5%; the exit's was 82.143%. These are short guest samples, not host CPU use or a capacity guarantee. There was no CPU pass/fail threshold.

An earlier control acquisition is retained as a failure, outside that comparison. It lost 87,337 switch frames, 161 packets at NFQUEUE and 17,695 of 361,952 useful UDP packets. The switch's pending queue reached about 3.09 seconds. It used small outer diagnostic captures; repeated trials omitted those captures. Their causal role in the overload was not established. The inner captures had no kernel drops and support the failed trial's separate delivery count. A single-move setup was also rejected by a private harness allowlist before load; allowing its existing zero-gap mode fixed that setup error.

## Timing the actual operations

Journald timestamps record receipt by the journal. The two private diagnostic builds add matching source timestamps to endpoint, accepted deferred-attempt and send events. Both builds contain the same diagnostics and differ only in the 100/10-ms maintenance period. They are research artifacts, separate from the retained runtime.

For a deferred attempt, eligibility starts after all three conditions hold: its pending deadline has passed, the previous global attempt is at least 250 ms old, and its target is the latest authenticated endpoint. The measured excess after that bound was 0.424 to 16.984 ms in controls and 0.485 to 9.435 ms in candidates. These bounds include endpoint commitment and lock time. The larger raw `due_late_ns` values also include waiting for the new endpoint and must not be called polling delay.

In the first diagnostic pair, the intermediate retry's excess fell from 16.984 to 1.641 ms. Final recovery followed the last authenticated endpoint closely: its excess after all conditions was 0.890 / 0.485 ms. Thus most of the response time in that pair lay elsewhere. Under jitter, another candidate's final endpoint arrived before the replay budget was available; endpoint-to-attempt time was 32.345 ms even though excess after eligibility was only 1.495 ms.

The same-VM packet timelines explain the remaining tail. One candidate request reached its final NAT mapping after 941.607 ms and received its reply 442.215 ms later, for a total of 1383.822 ms. In that trial B generated the inner echo reply in 11 microseconds. For a single change, the candidate maximum was 687.638 ms: 320.678 ms before the final NAT operation ended and 366.960 ms afterwards. These intervals come from the client VM's own clock. B's internal intervals use only B's clock; no cross-VM timestamp subtraction is used.

An IP/NAT mapping becomes usable only after a genuine encrypted client packet identifies it. A server cannot predict the next mapping. Replies already sent to an intermediate mapping cannot be recalled, and recovery still needs time to learn the final endpoint and traverse the return path. The measurements explain the observed tail; they do not establish a universal network lower bound.

## Retained change and cost

The runtime diff is one line in [coldwire_return_linux.go](flow-confirmation/coldwire_return_linux.go): `time.Tick(100 * time.Millisecond)` becomes `time.Tick(10 * time.Millisecond)`. It uses the same worker. Authenticated endpoint selection, current-key checks, source policy, 250-ms replay spacing, 500-ms ring age, 1100-ms pending lifetime and memory limits remain unchanged. A's 100-ms flow poll and C's 100-ms early-expiry margin are also unchanged.

Three ten-second idle samples measured B's Go process at 0.000/0.100/0.100% CPU with the old tick and 0.400/0.400/0.300% with the new tick. This is about 0.3 percentage points more on one core, with 10-ms accounting resolution and clients left running. The short sample does not establish a memory or long-term capacity effect. The small cost buys a finer check for an armed retry that receives no further client packet; it does not buy a fixed roaming deadline.

The uninstrumented candidate passed 39 top-level Go tests, with two upstream skips, and the Coldwire race tests. Each equal-diagnostic variant passed 40 top-level tests, the same two skips and the race tests. A private timing regression verifies that a 249-ms attempt is rejected and that an accepted 299-ms attempt records 49 ms after its deadline. The retained source hashes exactly match the tested uninstrumented candidate.

## Evidence and scope

[results-v35.json](results-v35.json) contains all qualified trials, the failed acquisition, exact operation events, source and capture hashes, build results and cleanup checks. These patches reconstruct the tested sources from the recorded baseline commit:

- [10-ms candidate](research/v35-maintenance-10ms.patch), also the retained runtime change;
- [timing control](research/v35-timing-control.patch);
- [timing candidate](research/v35-timing-10ms.patch).

All three patches passed application and byte-for-byte reconstruction checks. Existing reports and backing disks stayed unchanged. Cleanup restored ordinary DNAT, stock exit service, NAT, nftables rules, qdiscs and sysctls. Both native profiles passed probes afterwards. All four guests and the owned switch/seed processes are stopped; all 11 local ports are free. Personal JSON files stayed local, ignored and unchanged. No production server, user VPN, host network setting or GitHub state changed.

The prototype remains opt-in and outside the ordinary installers. This study did not test GUI clients, Internet DPI, IPv6 outer transport or a long soak. Finite admission, holding, recovery and client replay-window limits remain; repeated IP changes at high RTT can still produce responses later than one second.
