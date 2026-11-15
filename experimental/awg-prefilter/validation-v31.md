# v31: Late replies during rapid NAT changes

English | [Русский](validation-v31.ru.md)

**The remaining delay is not fixed.** A shorter, work-proportional replay
interval passed unit tests but failed the VM acceptance check. It did not
reliably reduce the 300-ms-RTT tail and produced more intermediate replays
when NAT changed faster. The prototype keeps v30's 250-ms pacing. The
[rejected patch](research/v31-work-pacing.patch) is retained for review,
not applied to the runtime. Normal installers still disable the prototype.

Production servers, the user's VPN and Windows networking were untouched.
The two native lab clients kept their binaries, profiles, keys and ports.

## What takes the time

The previous worst reply took 1594.138 ms. Its exit-side ICMP request and
reply were only 11 microseconds apart. Recovery send calls took about
10–20 ms. Waiting for a current authenticated endpoint, repeating ciphertext
that had already gone towards an obsolete NAT mapping, and the WAN path
account for the long tail; encryption was not a 1.59-second operation.

A separate diagnostic followed exact 32-byte ciphertext prefixes. One late
reply was sent to the original port, replayed towards two intermediate ports,
and finally delivered through the third changed port. All three intermediate
mappings had disappeared before the client could use those copies. Receiving
a fresh packet does not prove that the same NAT mapping will still exist
when a return packet arrives. A pending snapshot preserves another chance;
it cannot revive a closed mapping or predict the next address.

The prefix capture and diagnostic binary themselves overloaded the single-core
VMs. They are retained as path diagnostics and excluded from the performance
comparison. Their cross-VM timestamps do not establish precise link delays.

In that instrumented example, the client gateway completed its changes at
251.637, 535.937 and 823.787 ms after sending the probe. Ciphertext for the
three obsolete ports arrived at 384.883, 680.003 and 942.195 ms. The final
port received it at 1550.612 ms; plaintext appeared at 1555.335 ms. These
points use one client VM clock and do not depend on clock alignment between
VMs. They explain that example, not a general latency bound.

## Rejected candidate

The tested per-peer minimum interval was 50 ms. After a nonempty selection the shared
wait is the maximum of:

- 50 ms;
- `ceil(250 ms × selected packets / 8192)`;
- `ceil(250 ms × selected bytes / 16 MiB)`.

The entire selection is charged even if sending stops early. Only one send
can run at once. This preserves the previous actual upper work bounds of
32,768 packets/s and 64 MiB/s, plus one bounded initial batch. A full
16-MiB pending snapshot still incurs a 250-ms wait. No authentication check,
nonce challenge, conntrack-generation check, source-policy check or expiry
was removed. Retargeting still needs a fresh authenticated move and cannot
extend the original 1100-ms deadline. Stationary traffic cannot rearm it.

An earlier candidate used an 8-MiB denominator. A merged pending snapshot can
be 16 MiB, so that candidate imposed a stricter byte-work ceiling and could
wait 500 ms. Its valid trial is reported separately rather than hidden.
The final tested candidate used the existing 16-MiB maximum. Documentation now
distinguishes the 8-MiB immediate selection from a 16-MiB deferred attempt;
the older claim that every attempt was at most 8 MiB was incorrect.

## Matched VM measurements

All guests used Debian 13, kernel 6.12.116, one vCPU and 1024 MiB RAM under
QEMU/WHPX. No CPU quota or acceptance threshold was applied. The WAN model
requested 300-ms RTT and 30-ms normal jitter per direction. Each trial offered
6000 useful UDP packets/s and 25,000 noise packets/s from 16 IPs. Three gateway
IP/port changes used either a 250-ms or 100-ms requested gap. Client settings
were unchanged. The source and switch counts independently verify noise;
full source/destination sequence sets verify delivery after capture drain.

| Load / gap / run | Variant | UDP missing | ICMP >1 s | ICMP missing | Max RTT, ms |
|---|---|---:|---:|---:|---:|
| download 1200 B / 64 flows / 100 ms / 74 | v30 | 0 | 2 | 0 | 1125.539 |
| download 1200 B / 64 flows / 100 ms / 75 | candidate | 0 | 8 | 0 | 1226.666 |
| download 1200 B / 64 flows / 250 ms / 64 | v30 | 0 | 12 | 0 | 1514.487 |
| download 1200 B / 64 flows / 250 ms / 72 | v30 | 0 | 11 | 0 | 1673.953 |
| download 1200 B / 64 flows / 250 ms / 70 | candidate | 0 | 11 | 0 | 1569.105 |
| download 1200 B / 64 flows / 250 ms / 73 | candidate | 0 | 9 | 0 | 1575.727 |
| upload 128 B / 8192 flows / 250 ms / 66 | v30 | 0 | 0 | 0 | 734.197 |
| upload 128 B / 8192 flows / 250 ms / 77 | v30 | 0 | 0 | 0 | 952.481 |
| upload 128 B / 8192 flows / 250 ms / 71 | candidate | 659 | 2 | 1 | 1079.827 |
| upload 128 B / 8192 flows / 250 ms / 76 | candidate | 0 | 0 | 0 | 932.557 |

The one-second probe deadline is unchanged. Late means received after that
deadline; missing means absent from the complete capture, not just iperf's
own timing window. Runtime instrumentation and outer captures are absent
from these trials. Every listed acquisition has zero capture-ring, switch
and WAN-queue drops. CPU and memory samples, source hashes, exact movement
times and counters are in [the data](results-v31.json).

Across the two 250-ms-gap download controls, 23 of 200 replies were late;
the candidate had 20 of 200. Control maxima were 1514.487 and 1673.953 ms;
candidate maxima were 1569.105 and 1575.727 ms. Two runs per arm do not
establish a reliable tail reduction.

With the 100-ms requested gap, control selected 3010 + 4530 = 7540 packets
for two attempts. The candidate selected 3010 + 4027 + 4795 = 11,832 for three
attempts, including the intermediate mapping. That is 56.9% more selected
replay packets. Late probes rose from 2 to 8; the maximum rose from
1125.539 to 1226.666 ms. Extra work on transient paths is a plausible cause,
but the separate jitter realizations prevent a causal claim from one pair.
This result is sufficient to reject the proposed optimization.

One 8192-flow candidate trial lost 659 useful UDP packets and one ICMP
reply. It recorded 660 early ingress drops, while capture, switch, WAN and
NFQUEUE drop counters stayed zero. Conntrack reached its unchanged 8192-entry
capacity. The candidate repeat and both v30 controls had no unique UDP loss.
The pacing change is not established as the cause of that admission failure;
the failure remains evidence against a general loss-free claim.

## Checks and remaining limits

The candidate's small-snapshot regression fails on v30 and passes on that
candidate. Its suite passed 38 top-level Go tests with two upstream skips;
Coldwire race tests passed. A clean pinned AWG checkout received all eight
candidate helper/test files. This validates that experiment's implementation,
not its latency benefit.

A new retained regression checks that moves at 100 and 200 ms coalesce into
one retry to the latest address at 250 ms without extending expiry. It fails
on the rejected candidate and passes on the retained runtime. The retained
suite passed 37 top-level tests with two skips and all Coldwire race tests.
Its rebuilt runtime binary is byte-for-byte identical to v30. The research
patch replaces this guard with the candidate's opposite eligibility tests;
it is not a recommended deployment patch.

These trials do not establish a hard RTT bound or a reliable improvement in
the worst-case download tail. Arbitrarily rapid NAT changes can outrun return
traffic even with immediate server-side recovery. Conntrack/admission under
churn also remains a separate limit; no noise tuple received a trusted lease.
The trial count is too small to attribute every difference to pacing.
No Windows/macOS/Android/iOS GUI compatibility, IPv6, DPI resistance or
production DDoS capacity was retested. There was no new long-duration soak.

The next useful investigation is to trace entry-side admission and the
nonce/proof timeline with low-overhead bounded records, including late proof
and conntrack-eviction cases. Removing freshness checks or widening admission
would change the security model and is not justified by these measurements.

## Cleanup

Stock exit service, ordinary DNAT, original native profiles, observation
helpers, conntrack accounting and lab aliases were restored. Both native
probes passed before shutdown. All four VMs and owned switch/seed helpers
are stopped; eleven loopback ports are free. Backing disks, earlier reports,
personal JSON and Git HEAD are unchanged. No GitHub push was made.
