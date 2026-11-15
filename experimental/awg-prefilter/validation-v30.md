# v30: Conntrack churn, recovery bounds and helper restarts

English | [Русский](validation-v30.ru.md)

Four final trials delivered all **1,444,454 unique useful UDP packets**.
The five-minute run delivered all **1,800,004** more under four independent
noise schedules and twelve IP/NAT-port changes. Native clients kept their
binaries, profiles and keys. No fixed client IP or client-side helper was used.

There is still a latency limit: 23 of 400 frequent probes in the final
matrix arrived after one second. All 400 eventually arrived; the worst RTT
was 1.594 seconds. This remains a lab prototype, disabled in normal installers.
Production servers and the user's VPN were untouched.

## Problems and fixes

- A previously dumped the global conntrack table every 100 ms. More than
  4096 candidates could clear valid leases. It now uses exact original/reply
  tuple GETs, checks the generation again on confirmation and bounds its
  observed cache to 128 mappings. B supplies authenticated port hints; the
  holding process supplies early root-only candidates. Both still require
  the existing fresh nonce challenge and another authenticated B event.
- Unknown candidates could occupy pending challenges. Sixteen of 128 slots
  are reserved for authenticated hints and renewals; other candidates use
  at most four slots per learned source IP.
- First-packet discovery competed with new noise flows and missed reused
  NAT tuples with a live conntrack entry. Discovery now samples all unleased
  traffic, with 32/s and burst 256 per learned source, then 1024/s and burst
  1024 globally. Bulk retains 4976/s and burst 1024. The sum stays 6000/s,
  burst 2048. Discovery addresses expire after five idle seconds; the set
  holds at most 4096 addresses. A sample grants no trust.
- Holding used a linear search over 128 flow identities and an 8-MiB wire
  limit. A salted hash table now holds up to 8192 identities. Wire capacity
  is 16 MiB, with 8192 packets per identity. The global 32768-packet and
  one-second bounds remain. Kernel skb overhead is additional.
- B retained an 8-MiB reply history but selected at most 2 MiB for recovery.
  Attempts now allow 8 MiB; pending snapshots share a 16-MiB global limit.
  The 8192-packet limit, 500-ms ring age, 1100-ms pending deadline and 250-ms
  replay spacing are unchanged. Retargeting cannot extend a deadline.
- A listener missing at B's first notification permanently disabled proof
  events. Notifications now validate the current root-owned 0600 socket.
  A resends its holding-queue snapshot every 250 ms. The holding process
  safely replaces an orphaned root socket and refuses live or unsafe paths.
- Losing mTLS no longer clears still-valid leases immediately. They expire
  on their original deadlines and cannot refresh without a fresh proof.

Exact GET uses the kernel's tuple lookup rather than a dump.
[Linux conntrack implementation](https://github.com/torvalds/linux/blob/v6.12/net/netfilter/nf_conntrack_netlink.c).

## Final matrix

Four Debian 13 guests ran kernel 6.12.116 under QEMU/WHPX, each with one vCPU
and 1024 MiB. CPU had no quota or acceptance threshold. Noise was 25,000
256-byte datagrams/s from 16 IPs; useful UDP was 6000/s. Each case made
three gateway IP/port changes with a 250-ms gap. The WAN requested 300-ms
RTT with normal jitter of 30 ms in each direction. Native profile MTU stayed
1280; the largest useful payload was 1200 bytes.

| Direction | UDP bytes | Noise sockets | UDP sent / missing | Probes timely / late | A CPU mean / peak, % |
|---|---:|---:|---:|---:|---:|
| Upload | 128 | 8192 | 360,001 / 0 | 100 / 0 | 32.85 / 48.00 |
| Download | 128 | 8192 | 362,261 / 0 | 92 / 8 | 31.43 / 62.50 |
| Upload | 1200 | 64 | 360,006 / 0 | 99 / 1 | 26.64 / 46.15 |
| Download | 1200 | 64 | 362,186 / 0 | 86 / 14 | 25.45 / 44.44 |

CPU means use summed guest ticks over the recorded window; peaks use nominal
250-ms samples. Full samples, source rates, queue counters, hashes and memory
observations are in [the data](results-v30.json). All final cases had zero
NFQUEUE, netlink-user, capture, switch and netem drops, and no noise grants.
The entry's conntrack maximum remained 8192; the churn cases reached that
capacity. This did not cause the helper to clear authenticated leases.

The matched v29 upload with 8192 noise sockets lost 240,760 of 360,006 useful
packets. Entry CPU averaged 85.86%, peaking at 100%; the final candidate
averaged 32.85%, peaking at 48%. The 1200-byte v29 upload lost 41 packets,
with ten byte-bound drops recorded by the holding process. Its final counterpart lost none.
These comparisons cover the recorded lab; performance depends on the VPS and load.

Valid intermediate failures are retained in the data: B-only discovery lost
1036 packets; a small first-packet burst lost 39; an 8-MiB pending-reply
variant lost 88 large download packets. The final profile follows those
measurements. Historical v1-v29 reports were not rewritten.

## Independent-noise run and restart checks

Four processes each sent 6250 noise packets/s for 300 seconds, with bursts
of 257, 521, 769 and 1021 packets. They used 16 IPs and 64 sockets in total.
Useful upload used 512-byte datagrams at 5999.99/s. All
7,500,000 noise sends matched independent switch counts. There
were no queue, capture, switch or netem drops and no noise grants.

All 5983 captured ICMP requests with a complete one-second observation
window received replies; 2 took longer than one second, up to
1.144 seconds. A averaged 26.86% CPU
and peaked at 39.29%. Its minimum
MemAvailable was 659 MiB;
the minimum across all guests was 517 MiB.
No guest OOM was recorded. Longer runs are needed to assess memory growth.

The Go suite passed 36 top-level tests with two upstream skips; Coldwire race
tests passed. The large-packet regression fails with the old 2-MiB budget.
Python passed 14 helper and five netlink tests. Native checks covered the
base filter, grouped verdicts, handshake marks, holding bounds and lab tools.
The final holding self-test also passed AddressSanitizer/UndefinedBehaviorSanitizer.

Real kernel tests checked wrong generations, stale snapshots, the current
lease recheck, expiry, non-root denial, shutdown and an absent listener.
Lab-only systemd examples recovered all three helpers after SIGKILL in
1.09-1.80 seconds. Both quiet clients received 600/600 probes. A control
outage preserved old deadlines, then emptied the kernel set; reconnecting
restored leases without restarting AWG. Failure under attack was not tested.

## Measurement repairs

An inherited full guest filesystem, fragmented 1280-byte UDP and capture-ring
loss invalidated early acquisitions. The lab now checks free space. A compact
[collector](lab-switch/udp-capture.py) records actual counters and timestamps
inside GSO frames. Its final calibration matched a separate full capture's
5000 counters and timestamps exactly at both ends, with zero drops. Reducing
snaplen and retaining a 64-MiB ring avoided the small number of large capture
slots seen with the earlier configuration.
[libpcap ring allocation](https://github.com/the-tcpdump-group/libpcap/blob/libpcap-1.10.5/pcap-linux.c).

The first five-minute acquisition also hit a legacy rollback timer before
draining captures. Removing hooks flushed queued packets and exposed a fatal
`ENOENT` verdict handler. The repaired handler counts missing queue-101
verdicts; other errors remain fatal. A real hook reload produced ten such
errors without killing the process. Packets discarded by the hook change
remain lost. Later soaks replace both old timers with a bounded seven-minute
rollback. The induced teardown is excluded from delivery claims.
[Kernel verdict handling](https://github.com/torvalds/linux/blob/v6.12/net/netfilter/nfnetlink_queue.c#L1325-L1351).

iperf loss counts include reordering here. Delivery uses independently
captured actual sequence sets, a complete source count matching the sender,
and zero capture drops. Capture files and operational JSON remain private.

## Remaining limits and rollback

Discovery and tuple leases cannot authenticate every packet on A. More noise
sources can exhaust shared budgets or conntrack; spoofing a leased tuple
can consume B's authentication work. Buffers, the client's replay window
and proof deadlines still bound recovery. The latency result above remains
an open limitation. A five-minute run does not establish long-term stability.

GUI clients, IPv6, simultaneous moving peers and DPI behavior were not tested.
Strict I1/Jc drops and repeated return ciphertext still change wire patterns.
The normal installers remain unchanged; these results support further lab
evaluation rather than enabling the prototype on an active VPN.

Stock DNAT, original NAT/accounting settings, service definitions and both
native-client probes were restored before shutting down all four guests and
owned switch/seed processes. Parent disks, prior reports and personal JSON
hashes were unchanged. No Windows networking or GitHub state was changed.
