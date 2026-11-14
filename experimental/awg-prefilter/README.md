# AWG Header Protection + MAC1 prefilter

English | [Русский](README.ru.md)

This is a lab prototype for COLDWIRE's entry relay. It checks AWG headers
before forwarding packets to the exit. Existing AWG 3.1 clients keep their
profiles and need no extra software. The normal installers do not enable it.

The prototype uses one C process, OpenSSL 3 and nftables NFQUEUE. The entry
receives the HeaderProtectionKey and the exit's public key. It does not
receive the exit's VPN private key, client private keys, PSK or session keys.
User traffic remains encrypted between client and exit.

The separate [exit-confirmed flow experiment](flow-confirmation/README.md)
adds short kernel leases after B authenticates transport traffic. It needs
server-side changes on A and B, while clients keep their profiles and may
change IP or NAT port. [v18](validation-v18.md) records multi-flow noise,
cold connections, movement and the limits of tuple admission.

## What it checks

For incoming IPv4/UDP packets selected by the example rules, the process:

1. Checks IP/UDP lengths and reads the 12-byte AWG prefix as the ChaCha20 nonce.
2. Decodes the message type using HeaderProtectionKey.
3. For initiation and response messages, decrypts the protected handshake
   fields through MAC1 and checks it with keyed BLAKE2s-128. MAC2 and random
   trailers are outside this check.
4. Accepts recognized transport and cookie messages with sufficient length.
   The exit performs their authentication. Rejected packets receive no reply
   from the filter. Accepted packet contents are unchanged.

Only **S1-S4=12 and H1-H4=1,2,3,4** are supported. These are COLDWIRE's current
defaults. IPv6 outer transport and other parameter combinations are outside
this prototype. The process copies at most 212 packet bytes from NFQUEUE,
enough to read initiation MAC1 with a maximum-length IPv4 header. It checks
the copied length against the original length from `NFQA_CAP_LEN` and the
IP/UDP headers. The parser supports IPv4 options; Linux handles defragmentation
before the lab's raw-priority queue. NFQUEUE's GSO normalization stays enabled
so the process inspects individual datagrams.

This is not client authentication. MAC1 uses the recipient's public key;
Header Protection is an unauthenticated stream cipher. Captured handshakes
can be replayed through this filter. An observer can also reuse a captured
transport prefix/header with a modified payload. A holder of the shared
HeaderProtectionKey can construct recognizable packets without a registered
client key. B still rejects invalid VPN traffic.

I1/Jc packets do not authenticate and are dropped by this strict prototype.
They remain on the client-to-A link, but disappear from A-to-B traffic.
Successful VPN connectivity does not prove unchanged camouflage on both links.

The implementation follows the project's pinned AWG sources:
[header protection and handshake](https://github.com/amnezia-vpn/amneziawg-go/blob/1b86b2ae0e493e7ea93f8c1a0f0cb6735b1551f1/device/noise-protocol.go),
[MAC1](https://github.com/amnezia-vpn/amneziawg-go/blob/1b86b2ae0e493e7ea93f8c1a0f0cb6735b1551f1/device/cookie.go)
and [receive path](https://github.com/amnezia-vpn/amneziawg-go/blob/1b86b2ae0e493e7ea93f8c1a0f0cb6735b1551f1/device/receive.go).

## Build and offline tests

Use a disposable Linux VM. Build packages are needed only for compilation:

```bash
sudo apt-get update
sudo apt-get install --no-install-recommends gcc make pkg-config libc6-dev libssl-dev libnetfilter-queue-dev
cd experimental/awg-prefilter
make check
```

The tests use only Python's standard library. Synthetic public vectors in
`test-vectors.json` were generated independently with Python cryptography's
ChaCha20 and hashlib's BLAKE2s. They contain no operational credentials.
Checks cover malformed packets, altered handshakes, wrong keys, replay,
transport-payload tampering, key-file permissions and export restrictions.

For AddressSanitizer and UndefinedBehaviorSanitizer:

```bash
cc -O1 -g -std=c11 -Wall -Wextra -Werror -fsanitize=address,undefined \
  -fno-omit-frame-pointer prefilter.c -o prefilter-asan \
  $(pkg-config --cflags --libs libnetfilter_queue openssl)
ASAN_OPTIONS=detect_leaks=1 PREFILTER_BINARY="$PWD/prefilter-asan" python3 test_prefilter.py
```

For a separate profiling build, add `-DPREFILTER_PROFILE` to the compiler
command. Its reports include thread CPU nanoseconds spent receiving netlink
messages, inspecting packets, decoding headers, checking handshake MAC1 and
sending verdicts. Header and handshake times are included in inspection time.
Receive time includes the socket syscall and dequeue work. Clock calls add
overhead, so use the ordinary build for throughput comparisons.

## Grouping verdict messages

The optional build groups up to 16 individual verdict messages into one
netlink datagram. Each message names the exact ID of a packet that has
already passed inspection. Mixed accept/drop decisions, gaps and wrapped
IDs keep their individual verdicts. The queue's prefix-verdict API applies
one decision to every pending ID up to a boundary, so this build uses
ordinary `NFQNL_MSG_VERDICT` messages. [NFQUEUE API](https://www.netfilter.org/projects/libnetfilter_queue/doxygen/html/group__Queue.html).

```bash
make check-batch
```

This builds `prefilter-batch` and runs the protocol tests plus tests of the
encoded verdict messages and send-error handling. Use that binary with the
same `--vm-test --queue NUMBER KEYFILE` arguments as the ordinary binary.
The default `prefilter` build keeps individual submissions.

The grouped build uses `recvmmsg(MSG_WAITFORONE)` to receive one available
datagram and drain up to 15 more without waiting. It submits a full group
or the remaining tail before the next blocking receive. Receive storage is
bounded at 16 × 8192 bytes. A truncated netlink datagram or failed verdict
submission closes the queue. The existing fail-closed behavior then applies.
Kernel GSO normalization and the 212-byte packet-copy limit stay enabled.

`receive_calls` and `received_datagrams` describe receive operations.
`send_calls` counts submission attempts, including interrupted retries,
and `submitted_verdicts` counts individual verdicts successfully submitted
to the socket. Kernel forwarding and queue drops require separate counters.

## Disposable relay trial

Prepare an isolated client C, entry A and native AWG exit B. Use RFC1918
addresses, 1 vCPU and 1024 MiB per VM. First verify ordinary DNAT. The
following commands are for that lab, not an existing VPN.

On B, export the two filter inputs into a private directory:

```bash
sudo install -d -m 700 /root/prefilter-private
sudo python3 experimental/awg-prefilter/export_keys.py --vm-test \
  --state /etc/awg-relay-kit-exit/server.json \
  --output /root/prefilter-private/keys
```

The exporter refuses public exit addresses, unsupported S/H settings and
existing output files. Transfer the resulting file securely to A, preserving
root ownership and mode 0600. Its HeaderProtectionKey is secret; keep it and
packet captures outside Git. The filter refuses symlinks and readable-by-others
key files.

On A, start the separately built binary with:

```bash
sudo ./prefilter --vm-test --queue 100 /root/prefilter-private/keys
```

It prints `ready` and the copy limit after binding the queue. SIGUSR1 prints cumulative JSON
counters; SIGTERM prints the final counters and closes the queue. There are
no per-packet logs. `bytes` counts original packet bytes, `copied_bytes`
counts bytes delivered to userspace, and `netlink_enobufs` counts receive
overrun notifications. Read kernel queue-drop counters separately.
Queue length is bounded at 4096; fail-open is disabled. The previous
2048-packet bound overflowed under the verified burst workload in
[v11](validation-v11.md). This remains a finite queue, not a loss guarantee
for larger bursts or a stalled consumer.
The root process uses SO_RCVBUFFORCE to request a 4 MiB receive limit. Linux
reports 8 MiB after its accounting adjustment. This is a socket limit, not
resident process memory; kernel queue/socket memory is additional to RSS.

Before adding rules, arm an independent rollback that deletes **only** the
experimental table. Check and load a copy of
[lab-rules.nft.example](lab-rules.nft.example) after setting the lab interface,
addresses and ports. Keep the existing DNAT/SNAT rules intact.

The rules handle the case where a client's outer source port equals A's entry
port. Packets in conntrack's reply direction bypass the inbound MAC1 check because their
recipient is the client. Packets claiming B's address/port in the original
direction are checked after conntrack and before DNAT, rather than receiving
an unconditional source-IP exemption.

With the rules present, a stopped process or full queue drops traffic. To
return to ordinary DNAT, delete the experimental table **before** stopping
the process:

```bash
sudo nft delete table ip awg_prefilter_lab
```

Do not use COLDWIRE's whole-relay rollback for this comparison. The prototype
has no production installer, persistent service or automatic key-rotation
integration. Resource exhaustion and saturation of the VPS's external link
still require separate protection.

## Kernel rate guard

The optional [kernel guard example](lab-kernel-guard.nft.example) runs before
the queue and can also be tested with DNAT alone. It limits each source-IP
and UDP-source-port tuple to 35,000 packets/s with a 3500-packet burst, then
limits the aggregate to 50,000 packets/s with a 5000-packet burst. These are
lab settings. Measure clean traffic, including simultaneous clients, before
choosing rates for another environment.

The [protective admission example](lab-kernel-guard-protect15k.nft.example)
uses 15,000/s with burst 512 per tuple and 30,000/s with burst 2048 in aggregate.
In [v16](validation-v16.md), it preserved both clients under one offered
25,000/s noise flow by discarding excess before NFQUEUE. Legitimate high-PPS
clients receive the same limits. This remains a lab option; normal installers
do not load it. A static client-IP allowlist is not required.

The [multi-flow tests](validation-v17.md) found client drops and missing ping
replies when noise was spread across source ports, including trials below
the 90% CPU threshold. The shared aggregate bucket reserves no capacity for
authenticated clients. Check early client drops as well as NFQUEUE drops
before treating this guard as a protection policy.

Choose one guard example: both declare `awg_kernel_guard_lab`. To replace an
already loaded lab guard, check and apply one nftables transaction after
arming the rollback timer:

```bash
guard_replace=$(mktemp)
printf 'delete table ip awg_kernel_guard_lab\ninclude "%s/lab-kernel-guard-protect15k.nft.example"\n' "$PWD" > "$guard_replace"
sudo nft -c -f "$guard_replace" && sudo nft -f "$guard_replace"
rm -- "$guard_replace"
```

Run this from the example directory with matching lab addresses and interface.
For an absent guard table, check and load the chosen file directly.

Also count client-origin drops before NFQUEUE. In the
[burst study](validation-v4.md), tighter buckets removed queue overflow
while dropping some client packets earlier. Zero queue drops alone do not
establish that a policy preserves useful traffic.

The dynamic set holds at most 4096 tuples and expires an idle tuple after
five seconds. A full set drops packets from new tuples until entries expire.
Changing an IP or port creates a new bucket. Clients sharing a public IP have
separate buckets when their outer UDP ports differ. An attacker can still
fill the set or consume the shared rate budget, affecting legitimate users.

To compare the modes, load the guard table alone for kernel-guard/DNAT, then
load both example tables for kernel-guard/prefilter. Check each file with
`nft -c -f` before loading. Use the same lab interface and addresses in both.
Arm a rollback that removes both experimental tables. Restore DNAT by
deleting the tables.

```bash
sudo nft delete table ip awg_prefilter_lab
sudo nft delete table ip awg_kernel_guard_lab
```

Delete the tables that are present before stopping the queue process. The
normal relay table remains responsible for DNAT/SNAT.

## Authentication and camouflage decisions

The default C-only path checks every selected packet. The separate
[flow-lease variant](flow-confirmation/README.md) uses fresh authenticated
confirmation from B, tied to the exact conntrack flow and a short expiry.
A response-shaped packet or conntrack state alone can come from
unauthenticated traffic. Reused IP addresses must start a fresh check, and
one admitted client must never admit every client behind its NAT.

The C filter keeps its strict I1/Jc policy. Dropping those packets changes
the A-to-B packet pattern. In the flow-lease variant, an active lease bypasses
this check for its tuple. Camouflage on both links still needs measurement.

## Measurements

The [deferred-retry study](validation-v24.md) and [data](results-v24.json)
add one bounded pending ciphertext snapshot for the latest authenticated
address. With two NAT moves 250 ms apart at 300-ms RTT, UDP loss fell from
3768 to 1077 packets for IP changes, from 3491 to 982 for port changes,
and from 3358 to 663 for both. Loss and late replies remain. Ten primary
trials use the same corrected gateway model; the permissive-NAT failure
and preliminary trials are reported separately. Each VM has one vCPU and
1024 MiB, without a CPU threshold. Recovery stays off by default.

The [recovery boundary study](validation-v23.md) and [data](results-v23.json)
test the same 500-ms build at larger RTTs, repeated NAT moves and delayed
outbound discovery. The port-only move passed at 300-ms RTT; 600-ms and
1000-ms RTT left UDP loss. At 1400 ms, the helper's one-second TCP connect
timeout prevented startup before traffic testing. Recovery remains off by
default. CPU is recorded without a threshold.

The [return-recovery study](validation-v22.md) and [data](results-v22.json)
add an optional 500-ms ciphertext history on B. All six final trials
delivered 2,164,522 useful UDP datagrams, 1200 ordinary replies and 600
frequent replies without network loss, plaintext duplicates or late probes.
VMs retain one vCPU and 1024 MiB; CPU is informational in this stage and
peaked at 95.83%. Recovery is off by default. Repeated ciphertext changes
the wire pattern; DPI and unlinkability remain untested.

The [300-ms follow-up](validation-v21.md) and [data](results-v21.json)
shorten fresh-proof waits and prevent late transport counters from rewinding
B's return endpoint. All eight primary final-candidate runs had zero early
client discards and peak VM CPU at most 79.31%. The frequent probe still
lost replies around NAT moves. One extra diagnostic reached 92.86% client
CPU; the full lossless-service criterion remains unmet. Clients, C code
and admission rules are unchanged; this is a lab-only server patch.

The [WAN roaming study](validation-v20.md) and [data](results-v20.json) test
50/150/300-ms RTT with and without normal jitter. The unchanged v19 guard
had no client discards in 9 of 12 primary trials, but lost packets at
300 ms. A capture control received all 360,006 UDP datagrams inside B
while iperf reported 35 lost; two separate ICMP replies were lost after B.
Lossless roaming across the tested conditions is not established.

The [mobility study](validation-v19.md) and [data](results-v19.json) locate
early client losses before a changed source tuple receives its fresh proof.
The final rules give data a larger initial credit and limit unknown control
messages separately after C classification. All 12 qualified mobility trials
passed with zero client/NFQUEUE/UDP loss and peak CPU 78.26%. Client
profiles and the proof protocol are unchanged; v18 measurements are retained.

The [exit-confirmed flow study](validation-v18.md) and [data](results-v18.json)
test temporary admission after successful transport authentication on B.
They retain failures during development, cold-start and address-change
checks, and a reproduced source-spoofing limit. The ordinary installers
remain unchanged.

The [multi-flow and high-PPS study](validation-v17.md) and
[results](results-v17.json) extend the protective guard tests beyond one
noise tuple. They expose losses in the shared aggregate limiter and track
native client CPU separately from the relay. The lab switch's timing counter
now recognizes every source port from the isolated noise endpoint; its
forwarding path is unchanged. Initial acquisitions without native timing
were retained and repeated with the corrected counter.

The [NFQUEUE study](validation-v16.md) and [results](results-v16.json) confirm
client-origin drops when the shared queue fills. The optional protective guard
passed eleven 70-second trials with 25,000 offered noise packets/s: about
100 Mbit/s, 2200/2200 echo replies, no NFQUEUE or client-guard drops and peak
VM CPU 70.83%. It deliberately reduced admitted noise to about 10,280–12,835/s.
These are protective admission results, not capacity to inspect every offered
packet. Original-console and isolated source-IP/port-change checks also passed;
Multi-flow noise and clean high-PPS clients were outside that series;
[v17](validation-v17.md) tests them separately.

The [longer repeats](validation-v15.md) and [results](results-v15.json)
extend noise to 70 seconds and TCP to 60 seconds. All ten trials verified
25,000 offered packets/s, but none met the full service criteria. The helpers
and captures agreed on 1983/2000 replies; all seven filtered runs had
NFQUEUE overflow. A lighter collector reduced observation cost without
establishing repeatable service. The short v14 successes remain observations
of those runs; they do not establish sustained 25,000/s capacity.

The [Virtio and egress study](validation-v14.md) and [results](results-v14.json)
localize new output loss to entry's egress path. FIFO removed that deficit
in six controls but did not resolve their service failures; no NIC/qdisc
tuning was adopted. After correcting lab service lifecycle checks and
controlling host load, the unchanged defaults passed six short return
trials at 25,000/s and about 100 Mbit/s: 1200/1200 echo replies, peak VM CPU
60%. Failed acquisitions remain in the report; sustained VPS capacity is
not established.

The [recognizable-junk study](validation-v13.md) and [results](results-v13.json)
keep the 4096-packet queue: doubling it did not meet throughput/CPU criteria.
Random and invalid-MAC1 noise passed at 25,000/s; recognizable junk did not
pass reliably. Twelve final repeats at 15,000/s kept about 100 Mbit/s and
2400/2400 echo replies, with peak guest CPU 80.77%. Small exit noise-count
deficits and egress AQM drops remain explicit; this is not a lossless-relay
or production-capacity claim.

The [last-ping study](validation-v12.md) and [results](results-v12.json)
reproduce an early probe timeout while every reply reaches the client.
A bounded ICMP helper returned 1800/1800 in nine final runs at verified
25,000 noise packets/s and about 100 Mbit/s; peak whole-VM CPU was 65.38%.
A deliberate drop was still detected. The historical event lacks a capture,
so its exact cause remains an inference. VPN and filter code were unchanged
in this study.

The [QEMU send-path study](validation-v11.md) and [results](results-v11.json)
resolve the v10 rate shortfall in 33/33 noisy runs on the patched Windows
executable. Final repeats with the 4096-packet queue recorded zero overflow
drops, about 100 Mbit/s and entry CPU at most 48.15% under the 90% criterion.
One of 3000 final ping probes was lost. Patched-backend DNAT also passed;
earlier saturation does not establish an intrinsic filter speed advantage.

The [two-client and NAT-rebinding study](validation-v10.md) and its
[results](results-v10.json) use the revised 90% whole-VM CPU threshold.
All filtered trials kept about 100 Mbit/s total; peak guest CPU was 76.92%.
Active TCP survived three external-IP/port changes. Only 3 of 20 noisy
trials verified 25,000 packets/s, so repeatable pacing remains unresolved.
An immediate-send switch variant did not fix it and was not adopted.

The [native-switch study](validation-v9.md) and its [results](results-v9.json)
verify 25,000 offered noise packets/s. All six primary filtered runs kept
100 Mbit/s and stayed below 75% CPU on all four guests. DNAT saturated entry.
The [Windows lab switch](lab-switch/README.md) includes source, build instructions
and tests; VPS installers do not deploy it.
The [resident-collection study](validation-v8.md) and its [results](results-v8.json)
reproduce source-VM CPU spikes from new SSH/sudo collection. Persistent
launches kept all four guests below 75% in six filtered controls at verified
15,000 noise packets/s and 100 Mbit/s. The Python lab switch limited the
requested 25,000-packet/s runs; those remain diagnostics, not capacity results.
The [short-window CPU study](validation-v7.md) and its [results](results-v7.json)
record all four VMs: at 100 Mbit/s plus 10,000 noise packets/s, measured
windows stayed below 75% CPU. At 25,000 packets/s, DNAT saturated entry;
the filter preserved throughput in that comparison, but noise-VM peaks
failed the criterion for all four VMs. Kernel stacks include verdict reinjection
and Virtio transmission. The earlier large IFB CPU penalty did not repeat;
the mechanism behind the cross-study grouping difference remains unresolved.
The [CPU profiling study](validation-v6.md) and its [results](results-v6.json)
compare ordinary and timed builds. IFB reduced grouping; timing changed it
again. Recorded entry/exit/client CPU averages stayed below the study's 75%
whole-guest criterion; short peaks and noise-VM CPU were not measured.
The [bounded smoothing study](validation-v5.md) and its [results](results-v5.json)
add quiescent counter snapshots, actual-arrival captures and a switch
`TCP_NODELAY` control. IFB/TBF was not adopted: the tested queues added CPU
cost or client losses, and the UDP-port selector missed fragmented traffic.
The [burst and rate study](validation-v4.md) and its [results](results-v4.json)
compare four admission policies, including shared NAT and address changes.
No universal preset was selected.
The [verdict grouping experiment](validation-v3.md) and its
[results](results-v3.json) compare the optional build with individual submissions.
The [copy-limit follow-up](validation-v2.md) and its
[results](results-v2.json) cover the 212-byte copy and kernel guard.
The [original VM report](validation.md) and [results](results.json) cover
the earlier binary.
The report separates client interoperability, malformed traffic, flow-table
pressure and throughput. Its scope is the tested Linux client core; physical
Windows/macOS/Android/iOS GUI clients were not operated in these tests.
