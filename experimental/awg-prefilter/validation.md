# Prefilter VM results

English | [Русский](validation.ru.md)

Test date: **10 November 2026**. The prototype rejected the tested malformed
traffic and kept ordinary AWG clients working. Clean TCP throughput was close
to DNAT on this lab, while entry CPU use increased. Under a 60,000 pps flood,
the filter's queue dropped packets and useful throughput fell below DNAT.
The captured-header test also confirmed that this is not key-based client
authorization.

## Lab and method

Four local Debian 13.7 amd64 guests had **1 vCPU and 1024 MiB RAM each**:
client C, entry A, exit B and an independent noise sender D. C ran two issued
AWG 3.1 profiles in separate network namespaces. All used the project's
pinned native AWG core. Tunnel MTU was 1280; the filter required no new client
settings. Server software and user VPN settings outside the lab were untouched.

The entry used kernel 6.12.115+deb13.1-cloud-amd64, OpenSSL 3.5.7,
libnetfilter_queue 1.0.5, nftables 1.1.3 and GCC 14.2. QEMU 11.1.3 ran through
WHPX on Windows with CPU model `max` and the existing local reboot fix.
No WSL2 or Windows adapter/route changes were involved. The guests shared
a localhost-only learning Ethernet switch; all final runs recorded zero
switch queue drops. The prototype used one process and no Go SDK or Docker.
GCC was installed only for the disposable build/test.

For TCP, iperf3 ran between C's tunnel namespace and B's tunnel address.
Each mode/direction had three runs, each measuring 12 seconds after a
two-second warmup. Modes alternated DNAT/filter, filter/DNAT, DNAT/filter.
The CPU figures cover A's whole guest during the run, from `/proc/stat`.
RSS comes from the filter's `/proc` status. Source/binary hashes and all
individual measurements are in [results.json](results.json).

## Clean TCP

Values are medians of three runs. Upload means C→B; download means B→C.

| Direction | DNAT Mbit/s | Filter Mbit/s | DNAT entry CPU | Filter entry CPU |
|---|---:|---:|---:|---:|
| Upload | 234.61 | 233.45 | 3.25% | 33.10% |
| Download | 226.13 | 224.83 | 3.53% | 21.75% |

Filter RSS during these runs was **6.30–6.31 MiB**. This excludes kernel
socket/queue memory. The socket receive limit reported 8 MiB and the packet
queue was capped at 2048. These limits do not describe constant resident use.
The lab service also had a 64 MiB cgroup memory limit; the binary does not
install that service or impose that limit itself.

The near-equal throughput does not establish a maximum filter rate. QEMU,
WHPX, the software switch and the client/exit also constrain this lab.

## Noise while TCP was active

D sent a repeated 256-byte payload chosen randomly for each run. Requested
10k/30k/60k pps rates were achieved within 1 pps. Each row is one short run,
not a repeated capacity measurement. iperf3 measured eight seconds after a
one-second warmup inside the 12-second noise interval.

| Offered noise pps | DNAT Mbit/s | Filter Mbit/s | DNAT entry CPU | Filter entry CPU |
|---:|---:|---:|---:|---:|
| 0 | 232.76 | 209.18 | 2.04% | 29.68% |
| 10,000 | 182.54 | 178.93 | 2.40% | 33.47% |
| 30,000 | 134.75 | 153.69 | 10.21% | 46.74% |
| 60,000 | 162.68 | 125.42 | 59.70% | 66.67% |

The 60k filter run recorded **3281 queue drops**, with zero netlink receive
drops at the sampled point. Counters include noise and useful traffic;
they do not identify which packets were lost. Client probes passed after
each load case. Results are not monotonic and should not be extrapolated
to a provider link or an Internet DDoS attack.

## Rejection and flow pressure

Each selected payload was sent 9000 times at 3000 pps. Independent counters
on B measured arrivals. UDP GRO combines datagrams, so arrival counts were
derived from payload bytes after subtracting 28 bytes per counted IPv4/UDP
skb. The unfiltered control delivered all 9000 datagrams in every case.

| Input | Arrived at B, DNAT | Arrived at B, filter |
|---|---:|---:|
| Random payload | 9000 | 0 |
| Wrong HeaderProtectionKey | 9000 | 0 |
| Recognized header, invalid MAC1 | 9000 | 0 |
| Correct MAC1, invalid Noise initiation | 9000 | 9000 |
| Recognized transport header, invalid content | 9000 | 9000 |

With 40,000 noise packets across 4096 UDP source tuples, A's global conntrack
count changed **34→35 with the filter** and **37→4114 with DNAT**. SSH and
expiry of other entries also affect that global count. Early rejection
prevented the large accumulation seen in the control.

## Interoperability and limits checked

- Both issued native clients established fresh handshakes and passed HTTPS,
  DNS and 1200-byte DF ping tests. B-initiated handshakes exercised incoming
  response MAC1 checking.
- Switching a client's source IP and port worked. A client source port equal
  to A's entry port also worked.
- Wrong HPK and an unregistered client identity could not use the VPN.
- One hundred packets spoofing B's source address/port in the original
  direction were checked and dropped. The public nft example and exporter
  CLI were also used successfully.
- Killing the queue process stopped filtered traffic. Removing only the
  experimental table restored DNAT; the relay's stateless rules stayed equal.
- D had no key file and sent 100 packets made from a captured real transport
  prefix/header with altered payload. The prefilter accepted them; the
  legitimate client kept working. A received packet is therefore not proof
  of possession of a client key, or even of HeaderProtectionKey.

All **14 offline tests** passed in both optimized and ASan/UBSan builds,
including malformed input, independent crypto vectors and deliberate
replay/payload-tampering acceptance. `make -B check` passed. The existing
project's **48/48 Windows unit tests** also passed without skips.

## Reproduction and corrections

Build and export keys as described in the [prototype guide](README.md).
Use isolated private A/B/C/D guests and issued native profiles. Keep the
SSH management path outside the tunnel. On B, bind iperf3 to the tunnel:

```bash
iperf3 -s -B 10.8.1.1
```

On C, with the profile active in `pf-client1`, repeat these commands for each
mode. Add `-R` for download. Toggle only the experimental table on A.

```bash
ip netns exec pf-client1 iperf3 -c 10.8.1.1 -t 12 -O 2 -J
ip netns exec pf-client1 iperf3 -c 10.8.1.1 -t 12 -O 2 -J -R
```

Record A's `/proc/stat`, filter RSS and `/proc/net/netfilter/nfnetlink_queue`
before/after each run. For load, use a separate D and measure its achieved
send rate, switch drops and post-load client recovery. Never send the lab
noise workload to public endpoints.

The first private switch broadcast every frame and aborted on a full
buffer at a requested 100k pps. It was replaced by a learning switch with
bounded queues that drop frames instead of aborting. All final measurements
were repeated on that switch. Initial socket-buffer requests were also
subject to the kernel's ordinary receive limit. The final build explicitly
uses SO_RCVBUFFORCE and reports the resulting size; crypto tests and network
measurements were repeated. Repeat-run setup was corrected to replace an
existing lab IP alias. None of these changes touched the normal installers.

All guests and helpers were stopped and their localhost ports released.
Physical Windows/macOS/Android/iOS GUI clients, other distributions for this
prototype, REALITY coexistence, long traffic runs and DPI resistance were
not tested. The current filter drops I1/Jc on A→B and remains bypassable by
reused/crafted recognized packets. It is kept out of normal deployment.
