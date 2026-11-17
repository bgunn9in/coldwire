# V36: control recovery and a fatal NFQUEUE reply

English | [Русский](validation-v36.ru.md)

V36 fixes recovery of the helper connection and a separate failure in the main header filter. An nftables hook removal can discard packets that are still waiting in NFQUEUE. The old filter stopped when the kernel later returned `ENOENT` for a verdict on one of those packets. The fixed filter counts that specific reply and keeps running.

Seven final candidate trials completed on the original 1-vCPU, 1024-MiB lab VMs. Five delivered all 360,000 useful UDP packets. A deliberate twelve-second control blackout still lost 35,249 upload packets, and restarting A's helper lost 1,356. The work fixes persistent failures; finite holding and recovery windows still allow loss.

## What changed

The retained runtime changes are in [agent.py](flow-confirmation/agent.py) and [prefilter.c](prefilter.c). B's Go receiver, nftables admission rates, holding lifetimes and client wire format are unchanged from v35.

- A reconnects when a pending nonce has no acknowledgement by its existing three-second deadline. The check runs before expired requests are pruned. An acknowledged request without a data proof expires normally.
- B verifies a new connection with mutual TLS before replacing the previous stream. A bad certificate leaves the old connection intact. This lets an authenticated A replace a stale connection without restarting B's helper.
- A clears pending nonces and proof-order timestamps after a new authenticated TLS session. B can then restart its monotonic clock without having its new proofs rejected against the previous boot's timestamps. Old-session proofs still have no live nonce.
- A rechecks old observed mappings with exact conntrack GETs after ten seconds, at most sixteen per pass. The same live generation stays available for a new challenge; a missing or replaced generation is removed. This check grants no lease.
- An acknowledged, live nonce can request one held-packet probe without an earlier authenticated port hint. Generation checks, the shared 64/s burst-64 probe budget and bridge transport classification remain. A lease still needs B's fresh cryptographic proof. Hints retain their scheduling priority and reserved challenge slots.
- The main C filter accepts only `NLMSG_ERROR` with `-ENOENT` for an individual verdict belonging to its own queue as nonfatal. Wrong queues, other errors and malformed replies retain the failure path. The new `verdict_missing` counter records these replies; it does not restore a discarded packet or approve another packet.

## Measurements

Four isolated Debian 13 guests ran under QEMU/WHPX on Windows, each with one vCPU and 1024 MiB RAM. There was no CPU limit or CPU pass/fail threshold. Each trial sent 25,000 noise packets/s from sixteen IPs for seventy seconds and useful UDP at 6000 packets/s for sixty seconds. Nominal RTT was 300 ms, with 30-ms jitter in each direction on both VPN and control traffic. Three successive IP/NAT-port changes were separated by 250 ms. Only the disposable gateway changed mappings; the two native VPN clients kept their binaries, profiles, keys and listen ports.

Download used 1200-byte UDP payloads and 64 noise flows. Upload used 128-byte payloads and 8192 noise flows. The collision trial forced a translated-port conflict with the second native client. Fault trials also ran continuous native ICMP at 20 packets/s. The blackout dropped only A–B control TCP traffic for twelve seconds. Helper-restart trials restarted the named local process once.

| Scenario | UDP missing / 360,000 | Timely / captured replies, of 100 | Maximum RTT, ms |
|---|---:|---:|---:|
| DL, control blackout 1 | 0 | 90 / 100 | 1442.314 |
| DL, control blackout 2 | 0 | 90 / 100 | 1448.710 |
| UL, control blackout | 35,249 | 73 / 74 | 1082.061 |
| UL, SNAT-port collision | 0 | 99 / 100 | 1132.788 |
| UL, A helper restart | 1,356 | 100 / 100 | 865.238 |
| UL, B helper restart | 0 | 100 / 100 | 981.044 |
| UL, holding-process restart | 0 | 100 / 100 | 669.050 |

“Timely” uses the probe's one-second deadline. The captured count includes later replies; maximum RTT covers only replies that arrived. Thus 73 / 74 in the upload blackout also means 26 requests had no captured reply. Even the ordinary collision trial had one response later than a second, at 1132.788 ms.

All seven final trials passed source/noise-rate and complete-capture checks. No noise flow received a lease or entered the trusted path. Switch, netem, capture and NFQUEUE overflow counters were zero. Kernel purges are a separate event: the second download trial counted 683 vanished main-filter verdict IDs while delivering all useful UDP. Zero overflow counters alone would have missed that failure mechanism.

The largest recorded candidate CPU sample was 96.154%; the largest control sample was 100%. CPU summaries use all recorded guest trace samples, including collection edges. These short peaks and this finite workload do not establish VPS capacity or spare CPU.

Two matching control trials used the published v35 agent with the same corrected C filter. Download also had no UDP loss. Upload lost 53,947 packets versus the candidate's 35,249. The last missing packet was sent 4.006 / 0.464 seconds after a source-side marker collected following the unblock operation. There were 9761 / 0 missing packets sent more than two seconds after that marker. These are source-clock send times, not exact recovery or processing times; the marker RPC interval is retained in the data. Independent jitter and host scheduling, including the control's CPU peaks, prevent a universal percentage claim from this single pair.

## Isolating the failures

In a matched queue-purge test, the main filter was briefly paused with four packets queued. Traffic generation stopped before an unrelated prerouting hook was removed. The kernel queue became empty. The old diagnostic build received `NLMSG_ERROR`, decoded `-ENOENT` and exited; the fixed build counted four stale verdicts, stayed alive and passed a subsequent native-client probe. No post-failure native probe was attempted against the stopped old process. The old error path printed `errno` without decoding the kernel reply. Strings such as “Operation not supported” therefore did not identify the embedded kernel error.

The [kernel-error probe](research/v36-kernel-error-probe.c) separately obtains a real kernel reply for a nonexistent packet ID on an otherwise empty queue. It sends no test packets. In a disposable `kit-entry` VM, from this directory, build the current version with:

```sh
cc -O2 -std=c11 -Wall -Wextra -Werror -DCOLDWIRE_FIXED36 research/v36-kernel-error-probe.c -o /tmp/coldwire-kernel-error-probe $(pkg-config --cflags --libs libnetfilter_queue openssl)
sudo /tmp/coldwire-kernel-error-probe
```

For the old-code check, copy the probe into the same relative location in baseline commit `540d00e5a28eee508aba8fa05389b13678a85e8b` and omit `-DCOLDWIRE_FIXED36`. Root and the lab hostname are required. The old handler returned failure for the real `-ENOENT`; the current handler returned success without approving a packet.

An actual B guest reboot also reproduced the timestamp bug. The old agent rejected 32 valid post-query proofs whose new boot timestamps were lower. The final candidate accepted all sixteen observed lower-clock proofs. A's helper and both native client processes/files stayed unchanged during each reboot test. The final test additionally checked B's code/key-configuration hashes, a wrong client certificate preserving the old TCP connection, and a valid authenticated replacement followed by the original helper reconnecting. These reboot checks ran separately from the noisy WAN measurements.

## Validation and incomplete runs

The final agent passed 28 host tests and 28 Linux tests; conntrack passed five Linux tests. Four focused `serve()` regressions failed against the old source with assertion failures and no test errors. Linux `make check check-batch check-handshake check-escrow check-lab-tools` passed, including packet/mark checks, C self-checks and the new UDP tool. The netlink negative test also passed ASAN/UBSAN. Rebuilding the retained LF-formatted C source produced exactly the measured ELF.

Useful UDP now uses [udp-load.c](lab-switch/udp-load.c), which sends exactly 360,000 numbered packets without iperf's TCP control channel. Both interface captures and application counts determine loss. An early receiver requested 4 MiB through ordinary `SO_RCVBUF`, but Linux capped its reported buffer at 425,984 bytes; one trial lost 223 additional packets in that application socket. The final receiver uses its own `SO_RCVBUFFORCE` request and reports 8 MiB. No global sysctl changed. This fixes the lab receiver's measurement limit; real applications can still overflow their own buffers.

Five earlier iperf acquisitions timed out while waiting for results during faults; they provide no complete trial result. Six independent-UDP acquisitions failed the final native probe and retain partial delivery evidence. Another diagnostic run failed its nft syntax; one completed traffic and native probes but failed an unrelated timing postprocessor. Three early complete trials lack extra enrichment because the controller matched the previous study's filename prefix. Their sender/switch/capture data remain available; missing C statistics and journals remain null. Original main-filter crashes confound several early agent comparisons, so they are not presented as clean evidence for one controller change. The data keeps these runs separate from the final set.

## Evidence, cleanup and limits

[results-v36.json](results-v36.json) contains final/control trials, compact CPU summaries, exploratory and partial results, source/capture hashes, validation and cleanup receipts. [The retained patch](research/v36-retained.patch) reconstructs the runtime, tests and UDP tool from the baseline. Nine companion patches preserve the intermediate agents, equal-trace reboot builds, flow/main-filter diagnostics and the first UDP receiver. All ten passed application and exact canonical-LF reconstruction checks. Raw tested-byte hashes are included where line endings differed. Original captures and logs remain in the local lab archive.

After the user-requested pause, the same VM disks were restarted only for rollback and final probes. Ordinary DNAT, the stock exit service, original NAT, rules, qdiscs, sysctls and the original VM filter binary were restored. Both native profiles passed probes. All four VMs and owned switch/seed processes are stopped; eleven local ports are free. Backing disks, prior reports and personal JSON hashes are unchanged. Personal JSON stays local and ignored. No production server, user VPN, host network setting, commit or GitHub state changed.

The prototype remains outside normal installers. A twelve-second control outage exceeds the one-second holding window, helper restarts can lose packets, and kernel-purged packets cannot be recovered by handling their errors. Finite conntrack/challenge/replay budgets, spoofing of a leased tuple and application buffers still matter. The lab uses `S1–S4=12` and `H1–H4=1,2,3,4`; other AWG parameter sets remain unsupported by this filter. GUI clients, Internet DPI, IPv6 outer transport, sparse/idle-client recovery and a long soak were not validated here. There is still no one-second roaming guarantee.
