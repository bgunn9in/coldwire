# V37: wire parameters and A helper restarts

English | [Русский](validation-v37.ru.md)

The filter now reads AWG 3.1 padding, header ranges and trailer policy from its exported file. Keeping live kernel leases through a requested A helper restart removed useful UDP loss in six candidate trials. Two old-agent controls lost 2069 and 2409 packets. Abrupt termination during roaming still lost packets.

## Changes

`export_keys.py` exports S1–S4, H1–H4 and RandomTrailers alongside HeaderProtectionKey and B's public key. H ranges are disjoint inclusive uint32 ranges. S must be at least 12 and leave room for its message in an IPv4 UDP datagram. Partial sets, duplicate/unknown fields and invalid ranges are rejected. Old two-key files keep their previous defaults and trailer acceptance.

The C filter follows the pinned AWG receive order and checks MAC1 over the actual H value. It sizes the NFQUEUE copy to reach the configured headers and handshake MAC1. There is no new per-packet allocation. Default S=12 still copies 212 bytes.

| Fixture | S1 / S2 / S3 / S4 | H values | Trailers | Copy bytes | Fresh clients through filter |
|---|---|---|---|---:|---:|
| mixed | 32 / 48 / 64 / 80 | four disjoint ranges | on | 232 | 2/2 |
| equal | 96 / 96 / 96 / 96 | H1=0; includes high uint32 ranges | off | 296 | 2/2 |
| large | 1024 / 512 / 256 / 128 | four disjoint ranges | on | 1224 | 2/2 |

Full H ranges are in [test-wire-vectors.json](test-wire-vectors.json). These synthetic public vectors use independent Go x/crypto ChaCha20 and BLAKE2s implementations. [The generator](generate_wire_vectors.go) runs from the pinned AWG module; Go is optional for regeneration, not a new C runtime dependency. Tests cover range endpoints, equal/different prefixes, trailers, altered MAC1 and prefix copies.

Native checks restarted both unchanged Linux clients with separate lab profiles while the filter was already active. Fresh handshakes, successful probes and accepted initiation MAC1 were required. Baseline client profiles and binaries stayed unchanged. B used the same v35 receiver throughout. Normal installers do not enable this experiment.

A requested SIGTERM/SIGINT stop now leaves existing kernel/C grants at their original deadlines. The private status file records boot ID, relay scope, generations and monotonic deadlines. Startup checks owner/mode, a 256-KiB bound, age within ten seconds and matching scope. It intersects cached leases with both live kernel sets and exact conntrack GETs. nft JSON reports whole seconds; taking time before each query and rounding down conservatively shortens restoration. The cache grants no new authority and cannot extend expiry.

The final agent also keeps up to 128 untrusted observed candidates. It checks their original age and exact generation, then issues fresh nonces. Old proofs, pending requests, authenticated hints and proof-order timestamps are not restored. This repairs lost discovery state; the crash measurements do not show a reliable performance benefit.

Stopping A alone leaves fast-path grants until expiry, at most ten seconds. To revoke them immediately, stop A and atomically flush both trusted sets while retaining guard rules. C replay is rechecked against them. Full rollback returns ordinary DNAT. A kernel reboot changes the boot scope and destroys conntrack. These trials restart the helper process, not the whole A VM.

## Measurements

Four isolated Debian 13 VMs ran under QEMU/WHPX, each with one vCPU and 1024 MiB RAM, without a CPU limit. Every complete trial emitted 1,750,000 noise packets from sixteen IPs at 25,000/s over seventy seconds and exactly 360,000 useful UDP packets at 6000/s over sixty seconds. RTT was 300 ms with 30-ms jitter each way, including control traffic. The lab gateway made three IP/NAT-port changes 250 ms apart. Client files, programs and listen ports were fixed within each trial.

UL used 128-byte payloads and 8192 noise flows; DL used 1200 bytes and 64 flows. Noise retained S4 and its encrypted header, then filled the payload to 256 bytes. The generator and switch packet-size accounting stayed unchanged. Normal restart occurred around twenty seconds; SIGKILL around 25.35 seconds alongside roaming. Fault trials also sent native ICMP at 20/s.

| Scenario | UDP missing / 360,000 | Timely / all replies, of 100 |
|---|---:|---:|
| Old A, UL 1 | 2,069 | 100 / 100 |
| Old A, UL 2 | 2,409 | 97 / 98 |
| Initial cache, default UL 1 | 0 | 100 / 100 |
| Initial cache, default UL 2 | 0 | 99 / 100 |
| Initial cache, mixed UL | 0 | 100 / 100 |
| Initial cache, large UL | 0 | 99 / 100 |
| Final cache, equal DL | 0 | 94 / 100 |
| Final cache, default UL | 0 | 99 / 100 |
| Old A, SIGKILL + moves | 2,312 | 88 / 91 |
| Initial cache, SIGKILL + moves | 4,455 | 86 / 91 |
| Final cache, SIGKILL + moves 1 | 3,376 | 84 / 90 |
| Final cache, SIGKILL + moves 2 | 2,714 | 88 / 92 |

A timely probe arrives within one second; the second count includes later captured replies. All six candidate normal-restart trials delivered every UDP packet and all hundred probe replies. Some were late; their maximum RTT was 1314.814 ms. Final SIGKILL losses were 3376 and 2714, versus 2312 in the old-agent crash control. Independent jitter, host scheduling and a small sample prevent a crash-improvement claim. The initial cache's 4455-packet loss remains exploratory evidence.

All twelve accepted trials passed source/noise-rate and complete-capture checks. No noise received a lease or entered the trusted path. Switch, capture, netem and NFQUEUE overflow counters were zero. The largest CPU sample was 100.000%; minimum recorded available memory across all VMs was 478.0 MiB. Samples include collection edges and do not establish spare VPS capacity.

An earlier equal-prefix DL lost 137,587 UDP packets while the switch dropped 127,833 destination copies. Its client ring reached 4 MiB and stayed nonempty for 20.398 seconds. That acquisition is excluded, not treated as filter evidence. The repeat delivered all 360,000 UDP packets. The intermittent switch/QEMU receive stall was not reproduced or fixed here.

Three earlier acquisitions stopped on setup omissions: a missing UDP tool, an extra blank line in the lab key-transfer wrapper and a noise fixture exceeding 256 bytes after extending its prefix. All were fixed before retry and supply no complete result. A quiet probe also needed a closing-brace newline in its temporary nft table before measuring handshakes.

## Validation, evidence and cleanup

The final agent passed 35 host and 35 Linux tests; conntrack passed five Linux tests. A focused old-agent serve test fails with an assertion, without missing-method errors. Linux make targets `check`, `check-batch`, `check-handshake`, `check-escrow` and `check-lab-tools` passed. The 19 packet tests and netlink negative checks also passed ASAN/UBSAN. Rebuilding the main filter reproduced the measured ELF.

[The real-kernel probe](research/v37-lease-restore-probe.py) checks both timeout sets, cache permissions, boot mismatch, a phantom conntrack generation and natural expiry without packet hooks. Only in a prepared disposable `kit-entry` VM, after a native-client probe, run:

```sh
sudo python3 research/v37-lease-restore-probe.py --vm-test --agent-directory /root/flow-confirmation
```

[results-v37.json](results-v37.json) contains accepted and excluded acquisitions, source/capture hashes, CPU summaries, cold-connection tests and cleanup receipts. [The retained patch](research/v37-retained.patch) reconstructs code, tests and fixtures from commit `1b488685a980f81a0f6246ead4bf56280388e11a`. [The initial-agent patch](research/v37-initial-agent.patch) preserves the intermediate cache. Both passed exact LF reconstruction checks. Raw captures/logs stay in the local archive.

Ordinary DNAT, original VM rules/qdiscs/sysctls and the stock exit service were restored. Both original profiles passed probes; client file/binary hashes match the initial snapshot. The original main-filter ELF was reproduced and restored. All four VMs and owned switch/seed processes are stopped; eleven loopback ports are free. Backing disks, older reports and personal JSON hashes are unchanged. No production server, user VPN, host networking, Git commit or GitHub state changed.

The combined holding parser still limits IPv4 packets to 1536 bytes, even when the base header parser accepts larger parameters. Header Protection must be enabled. IPv6, GUI clients, Internet DPI, sparse/idle recovery and a long soak were not tested. Strict filtering still drops I/J camouflage between A and B. MAC1 and shared Header Protection are not client authentication; B remains responsible for cryptographic proof. SIGKILL during roaming, long control outages, finite holding/replay budgets and spoofed leased tuples remain limits. There is no one-second roaming guarantee.
