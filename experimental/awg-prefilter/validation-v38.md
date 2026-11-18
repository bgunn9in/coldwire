# V38: SIGKILL during roaming

English | [Русский](validation-v38.ru.md)

The rebuilt lab tests A's helper being killed during three changes of source IP and NAT port. The final four trials delivered all 1,440,000 useful UDP packets and all 400 ping replies. Of those replies, 66 arrived after one second; maximum RTT was 2190.656 ms. Normal installers still leave this prototype disabled.

## What changed

A connects and performs mutual TLS without blocking its event loop. It continues reading candidate notices and maintaining existing kernel leases while reconnecting. B retains its old authenticated stream until a replacement has passed TLS authentication. A also reads buffered application records immediately after a successful handshake.

After startup, A requests one bounded metadata refresh from the holding process. Root-only `CWR1` reannounces live flow identities; it neither releases packets nor grants trust. A caches at most four untrusted observations per learned source IP, with priority for live leases and authenticated hints. Rejected excess identities skip expensive conntrack lookups. Accepted candidates, probes and grants still require the exact current generation.

C holds packets for at most 2.6 s, up to 131072 packet IDs, 8192 flow identities, 16384 packets per flow and 32 MiB of wire bytes. Kernel skb overhead and netlink buffers consume additional memory. Verdict batches grew from 16 to 64 and the requested netlink receive buffer from 4 to 16 MiB. The probe takes the newest held packet. Probe budgets, nonce deadlines and kernel lease durations remain unchanged.

B gets a private replay filter derived from the pinned AWG implementation, with a 16320-counter window instead of 8128. This adds 1 KiB per keypair. The upstream client filter is unchanged. Duplicate and counter-limit rejection remain tested, and older accepted packets still cannot replace the endpoint selected by the highest counter. The wider window permits older previously unseen authenticated packets; a fresh proof timestamps their receipt on B, not their creation on the client.

## Intermediate results

The original-code controls lost 4169 and 1028 useful UDP packets. These runs use the rebuilt cohort, not old v37 measurements. The earlier unpublished lab directory was deleted; none of its missing raw evidence is presented as a fresh result.

A trace confirmed B rejecting successfully decrypted counters more than 8128 behind the latest counter. Widening that window alone still lost 1434 UDP packets. Metadata refresh alone also failed when noise displaced client observations. The per-source cache bound preserves discovery without a fixed client IP.

A 65536-packet holding queue overflowed 16596 times in `finalup2`, losing 3925 useful packets. Its measurement is valid; the failure is retained. The 131072 bound covers the tested workload with room for packets not yet read by C. A later 2.5-s candidate lost 122 UDP packets and one ping without queue, capture, switch or byte-limit drops. Old-flow confirmations arrived around 2.47 s after SIGKILL, before rule installation and C notification completed. Expiry is consistent with this timing, but the exact drop stage of those 122 packets was not captured. The final 2.6-s bound adds one maintenance interval and is tested separately.

One DL acquisition lost 9356 UDP packets while the switch dropped 6522 destination copies at its 4-MiB client output ring. It is excluded from filter conclusions. Its repeat `queuedown1200` delivered all UDP and ping. The underlying intermittent guest receive pause remains a lab limitation. Earlier full-noise pcaps also perturbed the queues; final trials use kernel noise counters and compact useful-traffic captures.

## Final trials

Every row includes 16 noise IPs at 25000 packets/s, useful UDP at 6000 packets/s,150±30 ms per direction, three NAT changes separated by a 250-ms pause, and automatic systemd restart after SIGKILL. Each VM has one vCPU and 1024 MiB; CPU is uncapped. Client programs, keys and profile bytes are unchanged. The A–B leg, including control TCP, carries the configured delay; client–A remains local. These are two native Linux AWG clients; GUI clients were not tested. The fixture uses Header Protection, S1–S4=12, H1–H4=1/2/3/4, Jc=0, random trailers and MTU 1280. Other wire-parameter parser tests still pass, but this new mobility cohort uses only that fixture.

| Case | Direction / UDP payload bytes | Missing UDP | Missing ping | Ping after 1 s | Max RTT ms |
|---|---|---:|---:|---:|---:|
| tailup128 | up / 128 | 0 | 0 | 24 | 2071.374 |
| tailup1200a | up / 1200 | 0 | 0 | 18 | 2190.656 |
| tailup1200b | up / 1200 | 0 | 0 | 12 | 2046.753 |
| taildown1200 | down / 1200 | 0 | 0 | 12 | 1268.608 |

CPU samples reached 100%. Minimum MemAvailable across the final cases was 305.8 MiB. The JSON records per-VM CPU, queue drops and memory observations. Full ICMP captures distinguish missing replies from replies that outlast the probe's own drain. Noise receives no authenticated lease in the recorded cases. These measurements do not establish spare CPU capacity or a one-second roaming guarantee.

## Verification and cleanup

All 41 helper tests pass on Windows and Linux; five conntrack tests pass on Linux. Linux make targets `check`, `check-batch`, `check-handshake`, `check-escrow` and `check-lab-tools` pass. The final holding self-test passes ASAN/UBSAN. A clean pinned AWG checkout passes `go test -p 1 ./...` with Go 1.25.0. Old-window and earlier agent regressions fail assertions before their fixes. The patcher refuses a dirty checkout and now runs `gofmt`; the first full Go check caught missing formatting. Exact final binaries were reproduced from the retained sources.

The four fresh Debian 13 VMs use kernel 6.12.117 and a local QEMU 11.1.3/WHPX build with the existing single-write patch. Installed QEMU and host networking were not changed. Cold ARP calibration lost 1899 datagrams, matching 1899 kernel unresolved discards; prewarming ARP delivered all 500000 calibration datagrams at the requested rate. The unpatched QEMU acquisition failed rate qualification and is excluded. No WHPX reset patch is applied in this rebuild; whole-VM reboot is outside this study.

[results-v38.json](results-v38.json) records accepted, failed and excluded cases, component/capture hashes, tests and cleanup. [The retained patch](research/v38-retained.patch) reconstructs code and tests from `e653d514cce099969f90d9c62272ab49dad9fa4c`. Raw logs, keys and disks stay in the ignored local lab. Old reports and personal routing JSON are unchanged.

Ordinary DNAT and the stock B receiver were restored; both original profiles passed probes. Removing the routed bridge changed A's MAC, so stale ARP entries on its lab peers were expired before the probes. Experimental hooks, queues and the routed bridge were removed, then all four VMs and owned switch/seed processes were stopped. The shared backing image's SHA512 matches its initial value. Production servers, the user's VPN, Git commits and GitHub state were not changed.

Longer outages, higher PPS, shared-NAT contention, spoofed leased tuples and link saturation can still defeat these finite budgets. IPv6, GUI clients, Internet DPI and a long soak were not tested. Strict filtering still removes I/J camouflage between A and B.
