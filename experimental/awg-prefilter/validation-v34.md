# V34: holding first packets after conntrack confirmation

English | [Русский](validation-v34.ru.md)

V34 adds an optional routed-bridge holding path and makes C's cached grants
expire 100 ms before the agent's lease. In the two final trials, all 722,058
unique useful UDP packets arrived. Six of 200 ping replies exceeded one
second; the maximum was 1302.170 ms. The prototype still has finite admission
and holding capacity, and it cannot guarantee a one-second roaming response.

The work used four isolated local Debian 13 VMs, each with one vCPU and
1024 MiB RAM, without a CPU limit. Existing servers, the user's VPN and normal
installers were unchanged. Measurements, source hashes, failed acquisitions
and cleanup checks are in [results-v34.json](results-v34.json).

## Why the first packet was lost

The original queue holds excess packets at IPv4 prerouting. A first packet
may reach it before conntrack confirmation. C rejects that metadata, and the
agent cannot find a confirmed generation to authorize while the packet is
held before the confirmation hook. Header Protection and MAC1 alone cannot
provide the missing client authentication.

A routed Linux bridge provides a later queue point: bridge postrouting runs
after L3 NAT and confirmation in this lab. The entry's lab address moves to
`cw34br`, with physical `enp0s3` as its port. Management stays on another NIC.
This is a lab network change, separate from the ordinary relay installer.

The optional [bridge rules](flow-confirmation/escrow-bridge.nft.example)
defer an unconfirmed overflow packet to queue 101 there. C checks the bridge
family and hook, confirmed non-dying ID, original/reply UDP tuples and actual
SNAT addresses. A installs IPv4 and bridge lease sets in one nft transaction,
then notifies C. A separate bridge chain checks the current generation again
before release. No unconfirmed entry receives a grant.

A forced test sends the first real encrypted packet of each new NAT flow
into holding. Client binaries, profiles, keys and listen ports remain
unchanged. The v33 control lost exactly three such packets. The corrected
bridge path preserved all three, including a test with forced SNAT-port
collisions: all 360,001 useful UDP packets and 100 timely ping replies arrived.
Kernel tests also accepted the correct generation and rejected a wrong ID,
an expired set entry and a deleted generation. Those four tests use root
fixture grants; they test the generation gate, not VPN authentication.

Direct netdev-egress NFQUEUE was rejected as an alternative. On this kernel,
`nft -c` accepted its syntax, but actual installation returned `Operation not
supported`. A syntax check alone did not validate that path.

## Two further fixes

The first bridge version classified all deferred packets before holding.
It delivered its useful UDP but dropped 56 packets in header queue 100.
The retained rules defer classification while a packet waits. An untrusted
probe still passes the unchanged header classifier before reaching B.
Bridge probes carrying handshake/control messages are dropped, preserving
the existing handshake allowance. C shares one 64/s, burst-64 probe bucket
across both holding paths. Its one-second holding window, 32,768 packet slots,
8192 flow identities, 8192 packets per identity and 16 MiB wire-byte limit
remain. Kernel skb memory is additional.

A forced test then exposed a rule error: `jump probe` returned to the
validation chain and fell through to its stale-drop rule. Two real packets
were lost despite C accepting them. Changing it to `goto probe` lets the next
base chain perform classification. Three additional kernel tests verify
transport classification, control-message rejection and malformed-header
rejection. Together with the generation cases, all seven passed.

Another qualified run lost five useful UDP packets at the original
prerouting lease gate, after the three first packets had passed. The flow
kept the same conntrack ID; C reported no expiry or generation rejection.
Agent traces show a short lease expiring and being renewed in that interval.
The evidence identifies a lease-boundary problem, but does not record the
exact kernel expiry time of each of those five packets.

A controlled test reproduced the underlying handoff race with a fixed
generation: the kernel set expired while C still had a cached grant. C
accepted the next packet and the kernel correctly dropped it. The retained
agent now encodes C's deadline one existing polling interval, 100 ms, earlier.
In the same test C held the packet, then released it after a fresh kernel
lease. The agent's lease and the kernel's intended deadline are unchanged;
authorization is not extended. A regression rejects the old encoding.
The shortened cache deadline is a conservative handoff margin, not an atomic
cross-process expiry guarantee under arbitrary scheduling stalls.

## Measurements and remaining latency

Noise was 25,000 packets/s from 16 IPs, using 64 or 8192 flows and bursts of
4096 packets. Useful UDP was 6000 packets/s, with 128-byte upload or 1200-byte
download payloads. VPN and control paths had nominal RTT 300 ms and normal
jitter of 30 ms per direction. Each run made three IP/NAT-port changes at
requested intervals of 100 or 250 ms. Entry conntrack capacity stayed 8192.

The data contains 15 qualified trials across intermediate and final stages.
Qualification requires exact per-source sender/switch noise counts, matching
offered arrival at A, rates within 1%, and zero switch, capture and WAN-emulator
drops. Conntrack drops before the IP observer are recorded separately.
Useful delivery is counted from complete unique sequence sets after draining;
iperf's provisional loss count is retained separately. No noise flow acquired
a lease or entered the trusted path in any qualified trial.

| Case | Useful UDP received/sent | Ping replies after 1 s, of 100 | Maximum RTT |
| --- | ---: | ---: | ---: |
| Forced first packets, v33 control | 359,998/360,001 | 0 | 851.072 ms |
| Forced first packets, bridge probe fallthrough | 360,000/360,002 | 2 | 1071.927 ms |
| Corrected bridge, SNAT collisions | 360,001/360,001 | 0 | 848.887 ms |
| Corrected bridge, before C expiry margin | 359,996/360,001 | 0 | 734.262 ms |
| Final C expiry margin, forced first packets | 360,001/360,001 | 0 | 858.819 ms |
| Download control, reduced diagnostics | 361,844/361,844 | 5 | 1318.155 ms |
| Final download, reduced diagnostics | 362,057/362,057 | 6 | 1302.170 ms |

The final download's worst reply took 1302.170 ms. On the client's clock,
the final NAT change ended 823.495 ms after that request; another 478.675 ms
elapsed before the reply arrived. B's inner request-to-reply interval was
10 µs on B's clock. These are separate single-VM measurements. Multiple moves,
path discovery, confirmation and return travel still consume time. These
trials do not demonstrate an overall improvement in download tail latency.

An early-probe experiment allowed one sample after the TLS request was
flushed, with one ACK-gated backup. All 27 unit tests passed, including blocked
TLS writes, bounded retries and rejection of pre-query events. Its upload
maximum was 727.677 ms versus 848.887 ms for the fixed post-ACK comparison.
Its download had eight late replies versus five, and no held packet was
available for an actual forward probe in that download. Independent jitter
and host scheduling differ between runs. The extra state and probe requests
are not retained; their [patch](research/v34-early-probe-rejected.patch) remains
an experiment. The runtime keeps ACK-only probes.

Mean whole-VM CPU in the two final trials was 45.04%/36.28% on A and
38.91%/66.46% on B. Some samples on other VMs reached 100%; no quota was applied.
A's minimum available RAM was 543,796 KiB. C's sampled high-water RSS was
2732/2788 KiB. Neither NFQUEUE had a drop. These are observations on this lab,
not a VPS capacity guarantee or a controlled CPU speedup result.

## Failed acquisitions and checks

Failures remain in the data:

* One control lost 683 noise packets in the attacker's default `fq_codel`,
  exactly accounting for the offered-noise mismatch. It also lost 4436 useful
  UDP packets; that separate loss's cause is unproved. Subsequent comparisons
  used bounded `pfifo limit 16384` only on the noise-generator VM.
* An initial bridge acquisition stopped at an observer assertion that had
  treated every physical-to-IP discrepancy as TBF loss. Its recovered core
  captures delivered all 360,002 useful packets. The observer now distinguishes
  earlier bridge/conntrack drops, with checks preserving legacy assertions.
* A download control dropped 4218 switch frames and lost 2384 unique useful
  UDP packets. It is excluded from filter comparisons.
* A full-diagnostic bridge download lost 14,610 packets in the outer capture
  itself. Its core captures were recovered, but no performance claim is made.
  Matched reduced-diagnostic downloads omit those outer captures and retain
  complete inner sequence and ping measurements.

Before the requested host reboot, a process launch returned Windows error
1455. The agent then shut down its owned VMs, interrupting acquisition.
Memory snapshots do not prove global RAM exhaustion. That interruption is
not evidence of a filter failure.

The current C source passed normal and ASAN/UBSAN self-tests. The current
agent and conntrack helper passed 25 tests; four verdict tests cover SNATed
probe marks and control classification. The header-filter runtime and B's
receiver are unchanged. Their earlier Go tests are recorded in
[v33](validation-v33.md) and were not rerun here.
Five [source-stage patches](results-v34.json) were applied to clean copies of
the stated baseline and every recorded source hash matched. The retained
runtime patch is [v34-retained.patch](research/v34-retained.patch).
Some early phase receipts record only runtime agent/C hashes. Their frozen
source snapshots are retained, but those old ELF builds were not reproduced
here. The final trials record public-source and runtime hashes.

The bridge, queues, experimental rules, aliases, WAN impairment, sysctls,
source qdisc and stock exit configuration were restored. Both unchanged
native profiles passed ordinary-DNAT probes before shutdown. All four VMs
and owned helpers stopped, all 11 loopback ports were free, and backing
images, previous reports and local personal JSON hashes were unchanged.
The cleanup snapshot was taken before the publication commit and GitHub push.

The bridge path has only been tested on the stated Debian 13 kernel. Missing
or dying generations, full tables, shared-budget exhaustion and finite
holding time can still lose packets. GUI clients, IPv6, DPI behavior,
production use and a new long soak were not validated. See the
[lab setup and rollback notes](flow-confirmation/README.md#optional-holding-after-conntrack-confirmation)
before any further isolated test.
