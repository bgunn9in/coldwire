# Exit-confirmed leases under multi-flow noise

English | [Русский](validation-v18.ru.md)

Test date: 13 November 2026. The new server-side prototype preserved both
already confirmed AWG clients against the tested 8- and 64-port noise. A
short kernel lease separates their work from the unknown-traffic budget.
Client applications, profile files and private keys were unchanged. A
learns a changed source address or NAT port after a new authenticated
confirmation from B. The final rules also gave cold clients an initial
allowance under the tested single-source noise.

Keep this experimental. Address changes still had transient client drops,
and a reproduced source-spoofing case can enter a leased tuple. Normal
installers are unchanged. [Implementation and lab setup](flow-confirmation/README.md),
[data](results-v18.json).

## Design and trust

B's patched AWG receiver emits a nonblocking local event only after
transport AEAD, replay checking and the inner source policy. Keepalives
are reported after AEAD/replay validation. A asks for a new event using
a random 128-bit nonce and its conntrack reply/NAT port. B must see that
event after the query; both timestamps use B's monotonic clock. Responses
use mutual TLS 1.3. A rechecks the current mapping before installing a
ten-second lease keyed by original source IPv4, UDP port and conntrack ID.
The new flow replaces the same peer's old lease. No client-IP allowlist,
client changes or VPN session/private keys on A are involved.

Revision 2 used an unknown aggregate 6000/s budget with burst 256 and a
ten-second lease. It preserved warm clients, but an initial cold attempt
got no lease under 64-port MAC1 noise. Revision 3 adds a dynamic unknown-source
IPv4 budget 1500/s with burst 64 before the aggregate. Ports from one source
share that allowance. Confirmed flows bypass both limits and NFQUEUE.
This source budget is admission fairness, not client authentication.

## Workload and acceptance

Four fresh Debian 13 COW guests each had 1 vCPU and 1024 MiB RAM, kernel 6.12.116,
QEMU 11.1.3/WHPX. A/B/C/D were entry, exit, two native profiles on one client
VM, and a noise generator. The existing corrected native switch observed
all noise source ports. Virtio RX/TX 256, NAPI 64, fq_codel, queue 4096, copy 212 and
grouped individual verdicts were retained. The C filter source/binaries
were unchanged; B alone used the pinned AWG Go notification hook. Go 1.25.12
built it with GOMAXPROCS=1, -p 1 and a 384 MiB Go memory target. Build time is
outside the load CPU qualification.

Noise was one source IPv4 with 8 or 64 UDP ports, total 25000 packets/s for 70 s,
256-byte payloads and bursts up to 4096. This is multiple tuples from one
machine, not a distributed multi-IP attack. Each completed bulk trial
matched sender/switch/entry 1750000 datagrams, no switch drops, complete native
timing and source/arrival means within 1% of 25000/s.

The two fixtures were valid MAC1 with invalid Noise content, and a freshly
captured transport prefix/header with altered ciphertext. Both pass the
header filter without authenticating at B. TCP requested 50 Mbit/s per
profile in mixed directions. UDP used 128-byte application payloads and
1000-us pacing, sixty seconds after one omitted second. Each profile sent
100 echo probes at 500-ms intervals with a one-second reply budget.

A full bulk pass required TCP within 5% of each target, or UDP sender within 1%,
receiver within 5% and zero reported loss. It also required 200/200 echoes
matching inner captures, zero early-client/NFQUEUE/netlink/shaper discards,
and every whole-VM CPU sample and four-sample window at most 90% on all four
VMs. CPU samples were nominally 250 ms. No quota, affinity, host network or
power change was made. No process census, NFQUEUE polling or fprobe ran
during load. Kernel counters count observed skbs; application UDP PPS is
not outer AWG wire PPS.

24 completed bulk trials; 17 full passes; 4789/4800 echo replies. They offered 42,000,000 noise datagrams. Two separate cold checks offered another 3,500,000 and returned 400/400 echoes.

## Final rules: steady traffic and movement

| Revision | Noise flows | Fixture | Useful traffic | Peak VM CPU % | Early client discards | NFQUEUE | Echoes | Full pass |
|---|---:|---|---|---:|---:|---:|---:|---|
| 3 | 64 | prefix | 50.00 / 50.00 Mbit/s | 38.46 | 0 | 0 | 200/200 | yes |
| 3 | 64 | prefix | 50.00 / 50.00 Mbit/s; move | 34.62 | 293 | 0 | 200/200 | no |
| 3 | 64 | prefix | 50.00 / 50.00 Mbit/s; move | 38.46 | 589 | 0 | 200/200 | no |
| 3 | 8 | prefix | 50.00 / 50.00 Mbit/s | 44.00 | 0 | 0 | 200/200 | yes |
| 3 | 64 | prefix | 1 × 6000 UDP PPS | 88.00 | 0 | 0 | 200/200 | yes |
| 3 | 64 | prefix | 1 × 6000 UDP PPS | 73.91 | 0 | 0 | 200/200 | yes |
| 3 | 64 | MAC1 | 50.01 / 50.00 Mbit/s | 41.67 | 0 | 0 | 200/200 | yes |
| 3 | 8 | MAC1 | 50.01 / 50.00 Mbit/s | 44.00 | 0 | 0 | 200/200 | yes |

The six steady trials passed the full criterion: 1200/1200 echoes, zero
early-client or NFQUEUE drops, useful rates at their targets, and peak
whole-VM CPU 88.00%. This includes two 6000-useful-UDP-PPS repeats
together with 64-port noise. The unknown allowance intentionally discards
most offered noise; this is not inspection of every offered packet.
Across the final eight trials, admitted noise averaged 674–725 datagrams/s.
The configured 1500/s source ceiling and burst 64 do not imply that every
4096-packet arrival burst can use a full second of that allowance.

Both movement tests ran under 64-port prefix noise with useful TCP active.
One changed source IP and client runtime UDP port; the other changed only
the gateway's public IP while keeping the native client port 32497. The
second test forced A to use a different SNAT port, proving that original
and translated ports must be distinguished. Profile files were unchanged.
A granted the new flow and removed the old one. TCP stayed near 50 Mbit/s
per profile. Together they returned 400/400 echoes and counted
882 early client discards before the fresh proof. These
transitions therefore do not pass the zero-early-discard criterion, even
where TCP and every echo survived. Seamless UDP migration is not established.

## Cold connections

Both native clients were stopped, A's leases cleared, and noise started
before the unmodified native profiles were started again. There was no
warm lease to inherit. Both obtained confirmations during load; captures
matched the probes, no early-client/NFQUEUE/netlink loss was counted, and
whole-VM CPU stayed at or below 76.00% including native startup and
SSH control. These are functional bootstrap checks without bulk traffic;
their complete counts do not establish a separate sustained-rate capacity.
Grant times in JSON are approximate differences of guest wall clocks and
are not a cross-machine latency guarantee.

| Fixture | Noise flows | Echoes | Early client discards | Peak VM CPU % |
|---|---:|---:|---:|---:|
| MAC1 | 64 | 200/200 | 0 | 76.00 |
| prefix | 64 | 200/200 | 0 | 73.91 |

## Earlier revision 2 measurements

Before adding the unknown-source budget, eight warm TCP repeats already
passed at about 100 Mbit/s total: 1600/1600 echoes, no early-client/NFQUEUE drops
and peak whole-VM CPU 44%. They are retained as a separate revision.

| Revision | Noise flows | Fixture | Useful traffic | Peak VM CPU % | Early client discards | NFQUEUE | Echoes | Full pass |
|---|---:|---|---|---:|---:|---:|---:|---|
| 2 | 64 | prefix | 49.99 / 50.00 Mbit/s | 40.74 | 0 | 0 | 200/200 | yes |
| 2 | 64 | prefix | 49.99 / 50.00 Mbit/s | 34.62 | 0 | 0 | 200/200 | yes |
| 2 | 8 | prefix | 50.00 / 50.00 Mbit/s | 30.77 | 0 | 0 | 200/200 | yes |
| 2 | 8 | prefix | 50.00 / 50.00 Mbit/s | 44.00 | 0 | 0 | 200/200 | yes |
| 2 | 64 | MAC1 | 50.00 / 50.00 Mbit/s | 36.00 | 0 | 0 | 200/200 | yes |
| 2 | 64 | MAC1 | 49.99 / 50.00 Mbit/s | 34.78 | 0 | 0 | 200/200 | yes |
| 2 | 8 | MAC1 | 49.99 / 50.00 Mbit/s | 33.33 | 0 | 0 | 200/200 | yes |
| 2 | 8 | MAC1 | 49.99 / 50.00 Mbit/s | 32.14 | 0 | 0 | 200/200 | yes |

Other revision 2 trials retain the failed legacy guard, high-PPS source-CPU
limit and movement losses:

| Revision | Noise flows | Fixture | Useful traffic | Peak VM CPU % | Early client discards | NFQUEUE | Echoes | Full pass |
|---|---:|---|---|---:|---:|---:|---:|---|
| 2 | 64 | prefix | 50.03 / 50.03 Mbit/s; move | 29.17 | 380 | 0 | 199/200 | no |
| 2 | 64 | prefix | 49.99 / 50.00 Mbit/s; move | 36.00 | 176 | 0 | 200/200 | no |
| 2 | 64 | prefix | 49.99 / 50.00 Mbit/s; move | 46.15 | 526 | 0 | 200/200 | no |
| 2 | 64 | prefix | 1 × 6000 UDP PPS | 65.00 | 0 | 0 | 200/200 | yes |
| 2 | 64 | prefix | 1 × 6000 UDP PPS | 71.43 | 0 | 0 | 200/200 | yes |
| 2 | 8 | prefix | 2 × 4000 UDP PPS | 96.30 | 0 | 0 | 200/200 | no |
| 2 | 8 | prefix | 2 × 4000 UDP PPS | 87.50 | 0 | 0 | 200/200 | yes |
| protect15k | 64 | prefix | 19.41 / 50.00 Mbit/s | 48.00 | 4466 | 0 | 190/200 | no |

Two profiles at 4000 useful UDP PPS each delivered without reported UDP loss,
but the first run reached 96.30% on their shared client VM and failed the
CPU criterion; the repeat peaked 87.50% and passed. The legacy protect15k
control lost ten echoes and discarded 4466 client packets while CPU stayed
below 90%. Zero queue drops did not make that control preserve service.

## Security checks and corrections

Six agent tests passed for post-query freshness, duplicate/out-of-order
proofs, NAT-port reuse with changed conntrack identity, expiry/bounds,
movement and buffered TLS records. The patcher accepted the exact clean
AWG revision, copied the hook/test and refused reapplication without
further mutation. The root Linux Go event test passed. A live TLS
connection without a client certificate was rejected.

Pausing A's helper with SIGSTOP for 12 s allowed kernel leases to expire
while traffic continued; resuming restored both clients. After stopping
both senders, 200 full captured ciphertext replays produced no new verified
event and no lease for the noise source. A single modified packet spoofing
an already leased IP/port bypassed A, was rejected by B and did not refresh
the lease. This confirms the tuple-admission limit; it is not a source-IP
spoofing defence.

The first 5-second lease revision passed one pilot, then expired during a 7.43-second proof
gap. A post-filter observer also misassigned five rejects; moving observation
before the queue established 214 true early-client drops in that aborted
workload. TLS reads were changed to drain buffered records, timestamps
made exact in nanoseconds, lease TTL changed to 10 s, and refresh retained
at roughly 2 s. A packet-local mark avoids a second lease lookup crossing
an expiry boundary between the guard and queue hooks.

One later load completed but settlement waited for all qdisc packets to
stop, which the persistent TLS channel prevents. Raw data was retained;
the check now waits for noise-specific counters, drops and queue depth.
Its replacement is the revision 2 MAC1/64 iteration 2 trial. The first cold
attempt without a source budget failed despite CPU headroom; no closing
packet trace isolated the failed handshake, so cookie/queue losses cannot
be assigned uniquely. Its failed source workload is retained separately.
A quiet capture warmup also needed a native reconnect retry after a cold
test; bounded retries now happen before noise and are recorded. None of
these attempts was silently relabelled a passing capacity test.

## Limits and rollback

The measurements cover two native Go profiles and one noise source IP.
Physical GUI clients, real VPS, distributed/spoofed IP floods, adaptive
cookie/MAC2 attacks, exhaustion of 4096-entry sets/candidate bounds and
hours-long operation remain untested. Too many conntrack candidates can
clear leases; the bounded control process is not an exhaustion defence.
Clients sharing a source IP share its cold allowance. A registered abusive
peer can retain a lease. Ingress bandwidth saturation remains outside
this admission mechanism. Unknown I1/Jc packets are still dropped, while
leased tuples bypass that check; camouflage against DPI is unmeasured.

Rollback restored B's stock binary and original service definition after
removing the temporary run-directory drop-in. Both original client
profiles passed ordinary-DNAT probes. Client NAT/runtime settings, console,
scheduler/netdev controls and the original guard template were restored.
Temporary tables/captures/helpers stopped. All four VMs and owned host
helpers stopped, and eleven loopback lab ports were free. Parent disks,
profile files, prior v1–v17 reports/data, filter/QEMU/switch and personal
JSON hashes matched. Live servers, the user's VPN, Windows networking,
affinity/power settings, WSL and GitHub were untouched.
