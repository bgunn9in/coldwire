# NFQUEUE overflow and protective admission

English | [Русский](validation-v16.ru.md)

Test date: 13 November 2026. A full NFQUEUE drops legitimate client traffic
along with noise. A kernel return trace confirmed 1342 client-origin drops
among 20,399 queue-overflow failures in one diagnostic trial.

An optional [protective guard](lab-kernel-guard-protect15k.nft.example) kept
useful traffic working in eleven trials with 25,000 offered noise packets/s:
99.99–100.05 Mbit/s, 2200/2200 echo replies, no NFQUEUE or client-guard drops,
and peak whole-VM CPU of 70.83%. It deliberately discarded excess noise before
NFQUEUE. This result establishes a tested admission policy for these workloads;
it does not establish capacity to inspect all 25,000 packets/s.

The filter remains experimental. Normal installers and the original guard
example are unchanged. [Measurements and checks](results-v16.json).

## Workload and acceptance

Four new COW guests each had one vCPU and 1024 MiB RAM. All reported Debian 13
kernel 6.12.116. They used QEMU 11.1.3/WHPX and the existing native switch.
The filter binary, AWG, native profile files and keys stayed unchanged.
Entry retained modern Virtio, RX/TX rings of 256, NAPI weight 64 and `fq_codel`.
The queue stayed at 4096 packets, with a 212-byte copy limit and grouped
individual verdicts. No CPU quota or affinity was applied.

Each of the 28 trials offered 1,750,000 UDP datagrams over seventy seconds:
25,000/s requested, fixed 256-byte payloads, one source tuple and bursts up
to 4096. Sender, native-switch and entry counts agreed in every trial;
switch drops were zero. Native arrival means were 25002.91–25010.09/s,
within 1% of the target. These means include bursts rather than describing
uniform packet spacing. The completed trials offered 49,000,000 datagrams.

Both noise fixtures passed recognizable-header checks: a valid MAC1 with an
invalid Noise body, or a freshly captured transport prefix with altered
payload. The exit still authenticates VPN traffic. Captured-prefix preparation
restarted a native client session before each capture and retained raw captures
privately. The noise guest needed no key file for that fixture.

Two native Linux clients requested 50 Mbit/s each for sixty seconds after a
one-second iperf omission. Each sent 100 ICMP requests at nominal 500-ms
intervals, with a one-second reply budget. A service pass required each TCP
stream within 5% of 50 Mbit/s, all 200 echo replies agreeing with captures,
no NFQUEUE/netlink/client-guard/client-shaper drops, and all whole-guest CPU
samples and four-sample windows at or below 90%. CPU was sampled nominally
every 250 ms, including observer cost; this is not an instantaneous CPU ceiling.
The eleven protective trials also had zero egress qdisc drops and zero settled
noise-count deficit between entry routing and exit ingress.

All runs used the lighter collector without a process census. Queue-depth
polling every 20 ms and scheduler accounting were reserved for diagnostics.
Seven diagnostic trials are excluded from service-capacity claims. Per-trial
JSON records their controls; twenty-one trials used capacity observation.
Watchdogs, client lifetime checks and fresh iperf listeners remained enabled.
There were no aborted workload attempts. Two setup errors before noise were
fixed: an expected offline rejection exit code was mishandled, and a
four-packet capture sometimes contained only obfuscation packets. The shared
check helper now accepts expected status 0/2; capture has a four-second time
bound without that packet-count cutoff. Failed captures were preserved.

## Queue failure and ping loss

The 20-ms diagnostics sampled queue depth 4096 and accounted for every queue
drop reported by the corresponding trial counters. Netlink user-drop counters
stayed zero. The consumer's cumulative scheduler wait increased by
10.45–12.97 seconds over the observed diagnostics, and sampler gaps reached
170.12 ms. Scheduler counters update when a task runs again; their deltas
must not be treated as exact wait time within each polling interval.
The observations support a burst and consumer-progress problem in the shared
queue. Average CPU alone does not guarantee that this queue drains in time.

A bounded fprobe on `__nfqnl_enqueue_packet` returned 20,399 failure records
in the final diagnostic, exactly matching its queue-drop counter. All returned
`-ENOBUFS` (`-105`) at depth 4096: 19,057 packets from the noise source and
1342 from the client source. The trace reported zero overrun, commit-overrun
and dropped events. A separate calibration paused the filter for 0.4 seconds;
its 8192 traced overflow events matched the queue counter. That one-second,
25,000-datagram calibration is excluded from the 28 workload trials.

Classification uses the IPv4 source header. UDP fields can lie outside the
linear skb head, so they were excluded from the published trace summary.
The trace does not join an encrypted outer packet to an individual inner
ICMP sequence. It proves that queue overflow reaches client-origin traffic.
The kernel's queue-full path increments `queue_dropped`; netlink delivery
failure uses a separate `queue_user_dropped` counter.
[Linux queue implementation](https://github.com/torvalds/linux/blob/v6.12/net/netfilter/nfnetlink_queue.c),
[fprobe return arguments](https://github.com/torvalds/linux/blob/v6.12/Documentation/trace/fprobetrace.rst).

Across all 28 trials, the probe and inner captures agreed on 5470/5600 replies,
with zero capture kernel drops. Of the 130 missing replies, 129 requests were
absent inside B's tunnel. One reply was visible inside B but absent at the
client in a failed console-only control. No captured client reply was merely
credited late or missed by the helper. The failed controls retain both
forward-path and return-path losses; aggregate queue counters do not assign
each missing ICMP packet to a particular discard.

## Controls and results

The original guard allows 35,000/s with burst 3500 per source-IP/UDP-port
tuple, then 50,000/s with burst 5000 in aggregate. The smaller-burst control
kept those rates and used bursts 1024/2048. The protective profile uses
15,000/s with burst 512 per tuple and 30,000/s with burst 2048 in aggregate.
These limits apply equally to noise and clients.

| Control | Runs | Total Mbit/s range | Peak CPU, any VM % | NFQUEUE drops | Echo replies | Full passes |
|---|---:|---:|---:|---:|---:|---:|
| Original guard, queue polling + schedstats (diagnostic) | 2 | 30.44–85.42 | 100.00 | 138475 | 386/400 | 0/2 |
| Filter nice −10 (diagnostic) | 2 | 30.42–75.68 | 100.00 | 350301 | 356/400 | 0/2 |
| Return, no queue polling, schedstats on (diagnostic) | 2 | 37.52–62.00 | 100.00 | 216777 | 372/400 | 0/2 |
| Original guard, schedstats off | 2 | 31.28–37.46 | 100.00 | 186281 | 383/400 | 0/2 |
| netdev_budget 64 | 2 | 29.32–30.32 | 100.00 | 163864 | 380/400 | 0/2 |
| Smaller bursts, original rates | 2 | 86.79–97.06 | 100.00 | 7154 | 400/400 | 0/2 |
| Console loglevel 4 | 2 | 68.73–100.00 | 100.00 | 13414 | 397/400 | 0/2 |
| Smaller bursts + console 4 | 2 | 89.47–96.49 | 100.00 | 457 | 400/400 | 0/2 |
| Protective guard, console 4 | 2 | 100.00–100.00 | 70.83 | 0 | 400/400 | 2/2 |
| Protective guard, up/down/mixed repeats, console 4 | 6 | 99.99–100.05 | 57.14 | 0 | 1200/1200 | 6/6 |
| Protective guard, original console 7 | 2 | 99.99–100.03 | 65.38 | 0 | 400/400 | 2/2 |
| Protective guard, source IP/port change, console 7 | 1 | 99.99–99.99 | 59.26 | 0 | 200/200 | 1/1 |
| Original guard + kernel return trace (diagnostic) | 1 | 45.93–45.93 | 95.45 | 20399 | 196/200 | 0/1 |

Increasing the filter's scheduling priority and lowering `netdev_budget`
did not solve the loss. Smaller guard bursts helped, but those settings
still failed the service criteria. Host load varied across sequential
controls; the two smaller-burst trials reached host peaks of 64.53% and
89.65%, so their difference cannot all be attributed to that rule change.

The serial log contained 1210 queue-full warnings. The kernel emits these
rate-limited warnings while holding the queue lock. Lowering console loglevel
from 7 to 4 kept warnings in the kernel log while suppressing their serial
output. This reduced loss in the observed controls, but did not produce a
full pass alone. Serial output can amplify a loaded queue; these sequential
trials do not establish it as the sole cause. The protective guard also
passed with the original console level, so it requires no console change.

## Protective policy and source changes

Across eleven protective trials, the early guard discarded 9,630,426 noise
datagrams. Admitted noise averaged 10280.19–12835.41/s, below the configured
15,000/s ceiling because the offered traffic arrived in bursts. Both the
offered and admitted rates are retained in the JSON. Useful traffic stayed
within its target, and client-origin early-drop counters were zero.

The six final repeats covered two uploads, two downloads and mixed directions
for both fixtures. Two further controls restored console loglevel 7. In the
last protective trial, client 1 changed its outer UDP port and its translated
source IP within the isolated LAN during mixed TCP traffic. Counters observed
the old tuple, new tuple and second client; both profiles stayed unchanged,
all 200 echoes returned and the service criteria passed. A static source-IP
allowlist was not used. A real public-IP change was not tested.

The [optional example](lab-kernel-guard-protect15k.nft.example) matches the
tested guard body. nftables syntax checking, atomic replacement of the
existing lab table and probes from both native profiles passed. Choose one
guard example; both declare the same table. Keep the existing rollback timer
and perform checks in a disposable lab as described in the [README](README.md).

## Decision and limits

Keep this policy as an experimental protection option. It bounds admitted
work before the shared queue without changing client keys or applications.
Legitimate high-PPS traffic receives the same limits, and multiple attacking
tuples can exhaust the shared budget or dynamic set. Before considering a
deployment, test several noise tuples and measure clean client traffic near
the limits. The filter still provides partial header admission; B performs
peer authentication.

These were seventy-second noise trials, with native Linux clients and two
fixed fixtures. Hours-long operation, physical GUI clients, real VPS, adaptive
or distributed attacks and DPI evasion were not tested. The strict prototype
still drops I1/Jc packets, changing the packet pattern between A and B.
The admission guard does not resolve that camouflage tradeoff.

Rollback restored ordinary DNAT, client runtime/NAT settings, scheduler and
console controls, and the original guard template. Both native profiles
passed probes. Temporary tables, captures and the owned fprobe were removed.
All four VMs and host helpers stopped; all eleven lab ports were free.
Parent disks, profile files, prototype/QEMU/switch binaries, prior v13–v15
reports and personal JSON hashes were unchanged. Live servers, the user's
VPN, Windows networking and WSL were untouched. GitHub was not updated.
