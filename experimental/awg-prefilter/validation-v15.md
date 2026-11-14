# Longer repeats at 25,000 packets/s

English | [Русский](validation-v15.ru.md)

Test date: 13 November 2026. The six short successes in
[v14](validation-v14.md) did not establish a sustained operating point.
Ten longer trials all verified the offered noise rate, but none met the
complete service criteria. The filter remains experimental and disabled
in the normal installers.

The main series used seventy seconds of noise with sixty seconds of TCP.
It exposed NFQUEUE overflow and real missing ICMP requests. Removing the
collector's process census reduced observation cost, while failures remained.
The prototype, queue size and Virtio settings were unchanged.

## Workload and acceptance

Four new COW guests each had one vCPU and 1024 MiB RAM. Their stopped parent
disks were hashed before and after the experiment and stayed unchanged.
Entry, exit and client ran Debian 13 kernel 6.12.116; the noise guest used
6.12.115. The Windows host used QEMU 11.1.3/WHPX and the existing native switch.
No CPU quota, affinity or host-network change was applied.

Each trial offered 1,750,000 UDP datagrams over seventy seconds at a requested
25,000/s: fixed 256-byte payloads, one source tuple and bursts up to 4096.
Two native Linux AWG clients requested 50 Mbit/s each, one upload and one
download, for sixty seconds after a one-second iperf omission. Each sent
100 fixed ICMP requests at a nominal 500-ms interval with the original
one-second reply budget. This spreads probes over about fifty seconds.
The sender's private duration bound increased from 30 to 90 seconds;
its packet format and pacing were unchanged.

The filter kept queue 4096, copy range 212 and grouped individual verdicts.
The guard kept 35,000/s with burst 3500 per tuple and 50,000/s with burst 5000
in aggregate. Entry kept modern Virtio, RX/TX 256, NAPI 64 and `fq_codel`.
Neither keys nor native profile files changed. Each captured-prefix test
recreated client 1's session and captured a new transport prefix before load.

A pass retained the previous criteria: each TCP stream within 5% of 50 Mbit/s,
200/200 echo replies agreeing with captures, no NFQUEUE/netlink/client-guard
or client-shaper drops, and every whole-guest CPU sample and sliding
four-sample window at or below 90%. CPU samples remained nominally 250 ms.
Observer cost is included; the threshold is not an instantaneous hardware
CPU ceiling. Noise guard and egress discards are recorded separately.

The job deadline increased to 100 seconds, the resident sample cap to 400.
Both native clients had at least two minutes left on their disposable service
lifetime before each launch; the lowest recorded remainder was over 104 minutes.
Both iperf listeners restarted before every trial. Capture and rollback
watchdogs covered the bounded load. There were no aborted workload attempts.
Two setup errors occurred before noise: copied seed metadata already existed,
and an inherited capture-directory name collided with an old run. Both were
fixed without deleting historical captures; they are recorded in the JSON.

## Rate and host controls

All ten trials counted 1,750,000 independently at sender, switch and entry:
17,500,000 offered datagrams in total. Sender and native-switch arrival means
were within 1% of 25,000/s, and switch drops stayed zero. Native arrival means
ranged from 25004.93 to 25009.82/s. These are whole-workload
means; the offered burst shape is not constant instantaneous pacing.

Every two-second host preflight stayed below 25% busy. The peak host load
within each trial ranged from 28.30% to 44.34%. None repeated
v14's fully saturated host condition. Aggregate host load does not rule out
contention on an individual logical CPU; host scheduling remains part of
this QEMU/WHPX result.

## Results

The first six trials tested random bytes with ordinary DNAT, valid MAC1 with
an invalid Noise body through the filter, and a captured transport prefix
through the filter, twice each. The second repeat reversed their order.
Three lighter-collector controls and one return control followed.

| Workload and collector | Runs | Total Mbit/s range | Peak CPU, any VM % | NFQUEUE drops | Echo replies | Full passes |
|---|---:|---:|---:|---:|---:|---:|
| Detailed: random/DNAT | 2 | 100.03–100.03 | 100.00 | 0 | 400/400 | 0/2 |
| Detailed: valid MAC1/invalid Noise | 2 | 60.61–100.48 | 95.45 | 18851 | 394/400 | 0/2 |
| Detailed: captured prefix | 2 | 84.40–100.34 | 100.00 | 23273 | 393/400 | 0/2 |
| Lean: random/DNAT | 1 | 100.03 | 95.83 | 0 | 200/200 | 0/1 |
| Lean: captured prefix | 2 | 92.07–100.35 | 91.67 | 18647 | 396/400 | 0/2 |
| Detailed return: captured prefix | 1 | 89.23 | 95.00 | 15193 | 200/200 | 0/1 |

The JSON retains each stream's non-omitted iperf intervals as well as its
mean rate. A mean near 100 Mbit/s does not describe a constant per-second
rate. Three of ten trials met the CPU criterion; other acceptance conditions
still failed. All seven filtered trials reported NFQUEUE overflow,
75,964 drops in total. Queue counters include both client and noise traffic;
they do not identify which individual packets were dropped.

## Ping and egress loss

The helpers credited 1983/2000 replies. All ten application results agreed
with the inner client captures, and every capture reported zero kernel drops.
For all seventeen missing replies, the request was visible at the client
but absent inside B's tunnel. This localizes the failure before the request
appears as decrypted traffic at B. It does not distinguish client encryption,
relay queues or B's receive/decrypt path packet by packet. There were no
cases of a captured exit reply disappearing only on the return path, or a
late captured client reply being misclassified as a physical loss.

Noise counters after A's filter and after routing agreed. Comparing the
routed count with raw ingress at B gave 886 missing normalized noise
datagrams across the ten trials; entry's root qdisc counted 928 drops.
Normalization remains `(bytes - 28 * skb_packets) / 256`. Both raw fields
are retained, since B may group multiple UDP datagrams into one skb.
The qdisc carries legitimate traffic as well, so its aggregate discards
must not be assigned directly to specific missing noise or ICMP packets.

## Collector control

Detailed collection walked `/proc` every quarter second to attribute CPU
ticks to processes. The lighter control disabled that census on all four
guests. Whole-VM `/proc/stat` CPU, qdisc sampling, workload timing, counter
snapshots and ICMP captures were retained. The return control re-enabled
the census. Its state is recorded per role and trial.

For the captured-prefix comparisons, entry collector cost was approximately
2.16–2.44% of one core with details and 0.21–0.27%
without them. These estimates divide total collector CPU time by its observed
collection span. They are not filter CPU measurements. Workload timing still
varied between sequential trials, so the difference in overall guest CPU
cannot all be assigned to the census.

One lighter captured-prefix repeat reached 100.35 Mbit/s,
returned all 200 echoes and kept peak CPU at 80.95%. It also lost
9260 packets at NFQUEUE and therefore failed the full criterion. The adjacent
lighter repeat and the return to detailed collection also failed. Removing
observation cost is useful for future measurements; it has not established
repeatable 25,000/s service.

## Decision and cleanup

Keep the prototype experimental, queue 4096 and current NIC/qdisc defaults.
Use the lighter collector for capacity repeats, reserving process attribution
for separate diagnostics. The next useful observation is a time series of
NFQUEUE depth and drop events alongside the missing requests. Keep queue 4096
and 25,000 offered packets/s in that comparison.

Each noise run lasted seventy seconds; continuous hours-long operation was
not tested. Physical GUI clients, changing external IPs, real VPS and
DPI evasion were not tested. The tested admission check still does not
authenticate a peer; the exit performs VPN authentication.

Rollback restored ordinary DNAT and client runtime/NAT settings. Both native
profiles passed probes, and profile, prototype, baseline QEMU, switch and
personal JSON hashes matched their original values. Temporary tables and
captures were removed; all four guests and owned host helpers stopped,
with all eleven lab ports free. Parent disks and prior v13/v14 reports were
unchanged. Live servers, the user's VPN, WSL and Windows networking were
untouched. GitHub was not updated. [Results and checks](results-v15.json).
