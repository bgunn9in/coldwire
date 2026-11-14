# Reducing admission delay and return-path losses at 300-ms RTT

English | [Русский](validation-v21.ru.md)

Test date: 14 November 2026. Faster fresh-flow confirmation removed the
entry's early client discards in all eleven runs of the final candidate.
Eight primary runs stayed below 90% CPU on every VM, with a maximum of
79.31%. Return-path losses around a NAT move remain: the frequent probe
received 95 or 96 of 100 replies with jitter, and 93 without jitter.
The prototype remains a lab experiment. See [data](results-v21.json) and
the [previous WAN study](validation-v20.md).

One additional diagnostic reached 92.86% CPU on the client VM. It fails
the CPU criterion; a repeat at 72% does not erase that failure. None of
the sixteen runs meets the full lossless-service criterion when the new
frequent probe is included.

## Setup and measurements

Four fresh Debian 13 COW guests used QEMU 11.1.3/WHPX, kernel 6.12.116,
one vCPU and 1024 MiB RAM each. The Windows switch and QEMU binaries were
unchanged from v20. Native AWG client binaries, profiles, keys and ports
32497/32498 were unchanged. The client gateway changed profile 1's source
IP, or its IP and NAT port, at second 25 of useful traffic.

Each run offered 25,000 noise datagrams/s for 70 seconds from 64 ports
at one address, in 4096-datagram bursts. Noise reused a captured transport
prefix with altered ciphertext. Useful upload sent 6000 UDP datagrams/s
with 128-byte payloads for 60 seconds, using `iperf3 -u -b 6144000 -l 128
--pacing-timer 1000 -t 60 -O 0 -J`. PPS counts application datagrams;
offloads can combine them into fewer skbs or outer packets.

Netem added 150 ms in each A-B direction. The jitter variant added normal
variation of 30 ms per direction, with no configured loss. VPN traffic
and the mutual-TLS control channel traversed these queues. Each queue
had a 16,384-packet limit. Twenty physical pings checked RTT before each
run; the primary medians ranged from 296 to 321 ms. Seeds and individual
samples are in the data. Management and the noise-to-entry path had no
added delay.

Both profiles sent the usual 100 probes at 500-ms spacing. A separate
profile-1 probe sent another 100 at 50-ms spacing, starting at second 23,
with a one-second reply deadline. Its five-second window brackets the
move. Captures distinguish its ICMP identifier from the ordinary probe.
This makes the acceptance check more sensitive than v20's ordinary ping.

Whole-VM CPU includes every stored nominal 250-ms sample from noise
startup to collection end, plus every rolling four-sample window. No
runtime quota or affinity change was used. Only compilation and Go
regression tests used a temporary 80% CPU quota and 768-MiB memory bound,
with no traffic measurement running at the same time.

All sixteen runs qualified the offered noise rate within 1%, accounting
for 28,000,000 datagrams. Capture, NFQUEUE, netlink and netem queue drops
were zero. Noise obtained no authenticated lease. Full service acceptance
also requires useful rate, zero reported UDP loss, both probe sets fully
delivered, zero client/control guard drops and every VM at or below 90%.
Its result is 0/16; the narrower improvements below do not imply a pass.

## Changes and controls

The C classifier and nftables admission rules are unchanged. Unknown
traffic still has 1500/s with burst 4096 per source, then 6000/s with
burst 1024 in aggregate. Control-message limits, ten-second leases and
all freshness checks remain in place.

The `fast` control changes A's conntrack poll from 250 to 100 ms, applies
an accepted confirmation to nftables immediately, and uses `TCP_NODELAY`
on the TLS stream. B's same-endpoint notification interval changes from
250 to 50 ms. The old loop could record a confirmation and wait another
poll before applying it. Reducing these waits preserves the requirement
for a fresh authenticated B event after each nonce request.

The `new` candidate also selects return endpoints by the greatest accepted
transport counter in the current keypair. A late lower counter cannot
rewind the endpoint or produce an old-path proof. The counter epoch uses
the keypair's creation time and local index; it resets for a new current
keypair, including counter zero. Older valid payloads still undergo normal
processing and delivery. The receiver retains no extra keypair pointer or
session secret. Existing authentication, replay and AllowedIPs checks,
timers and the disabled-roaming setting remain in use.

`old` uses the archived v20 code. `fast` keeps its endpoint selection.
`new` includes both changes. These short comparisons establish bounded
behavior, not a statistical loss-rate estimate.

| Variant | Jitter ms each way | Move / repeat | Entry client discards | Frequent probe / 100 | Ordinary / 200 | iperf reported loss | Peak VM CPU % | Fresh grant ms* |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| old | 30 | IP / 0 | 1705 | 90 | 199 | 1741 | 71.43 | 1028.6 |
| old | 30 | IP + port / 0 | 83 | 94 | 200 | 128 | 77.42 | 654.3 |
| fast | 30 | IP / 0 | 0 | 92 | 200 | 78 | 82.14 | 468.1 |
| fast | 30 | IP + port / 0 | 0 | 95 | 200 | 56 | 62.50 | 266.9 |
| new | 30 | IP / 0 | 0 | 95 | 200 | 67 | 79.31 | 395.5 |
| new | 30 | IP + port / 0 | 0 | 96 | 200 | 8 | 52.63 | 365.6 |
| new | 30 | IP / 1 | 0 | 95 | 200 | 75 | 74.07 | 405.7 |
| new | 30 | IP + port / 1 | 0 | 95 | 200 | 169 | 61.11 | 317.5 |
| new | 30 | IP / 2 | 0 | 96 | 200 | 17 | 77.42 | 458.6 |
| new | 30 | IP + port / 2 | 0 | 95 | 200 | 184 | 77.42 | 361.9 |
| new | 0 | IP / 0 | 0 | 93 | 200 | 0 | 75.86 | 401.9 |
| new | 0 | IP + port / 0 | 0 | 93 | 200 | 0 | 64.71 | 349.3 |

*Grant time compares helper-history wall time on A with the gateway's move
completion on C. It is approximate across guest clocks and does not trace
the exact nftables commit. The runtime test separately checks that accepted
confirmations and disconnects update the kernel before the next poll.

The eight primary `new` runs received 1600/1600 ordinary replies. Their
full-window CPU peaks were A 48%, B 37.04%, client 79.31% and noise 14.81%.
They had zero early client/control guard drops. Ordinary ping alone misses
some losses in the short interval around the move.

## Return path

Outer captures matched B's reply payload prefix at A and in the client
gateway's ICMP port-unreachable quote. Those packets reached the old
gateway destination `192.168.76.30:32497` after the NAT move. Inner captures
show that B had received the requests and generated replies. The entry's
forward admission counters cannot detect these return-path losses.

Four additional diagnostics captured the first frame on B's post-netem
IFB transmit path with the new translated source port, then checked that
port against the exit-confirmed conntrack mapping. Timing comparisons use
the same B clock. The transmit tap precedes IFB reinjection into receive
processing; see Linux's [transmit tap](https://github.com/torvalds/linux/blob/v6.12/net/core/dev.c)
and [IFB reinjection](https://github.com/torvalds/linux/blob/v6.12/drivers/net/ifb.c).

| Diagnostic | Entry discards | Frequent / 100 | Peak VM CPU % | Return replies generated before first new-path frame |
|---|---:|---:|---:|---|
| old, IP, repeat 0 | 111 | 93 | 78.57 | 6/7; one reply 30.360 ms later |
| new, IP, repeat 0 | 0 | 95 | 92.86 | 5/5, 55.288 to 213.581 ms earlier |
| new, IP, repeat 1 | 0 | 94 | 72.00 | 6/6, 28.870 to 225.054 ms earlier |
| new, IP, UDP capture | 0 | 96 | 76.19 | 4/4, 14.928 to 217.927 ms earlier |

The old observation is consistent with late-path processing. This tap
does not record the AWG endpoint write or decryption, so it alone cannot
prove an endpoint rewind. Unit tests directly reproduce and prevent that
rewind for reordered counters, batch tails and old keypairs. In all three
new diagnostics, the missing return replies were generated before the
first new-path frame reached this tap. Changing endpoint selection cannot
redirect packets already encrypted and sent towards the old mapping.
Recovering those replies would need a separate buffering/retransmission
design; this change adds neither.

## Useful UDP accounting and CPU exception

The UDP-capture diagnostic found all 360,000 unique source datagrams
inside B after decryption, with zero missing sequences, duplicates or
capture drops. Iperf credited 359,838 and reported 162 lost. That case's
reported loss is receiver accounting, not loss through the tunnel.
Other cases retain their raw estimates; they did not capture every useful
datagram, so the same conclusion is not asserted for each of them.

The 92.86% client-VM sample lasted 249.899 ms, 7.25 seconds after collection
started and before the move. Its tick deltas were user 4, system 12,
softirq 10, idle 2. There is no per-process profile that establishes the
cause. The repeat reached 72%, and the separate UDP capture reached 76.19%.
The cause of the original spike remains unresolved. Thus all eight primary
runs pass the CPU bound, while the complete diagnostic set does not.

## Regression, security and rollback

The patched pinned source passed sixteen top-level Go device tests,
including AWG/two-device ping, up/down, concurrency and the three hook
tests. Upstream still skips `TestAWGHandshakeDevicePing` as manual-only and
`TestWaitPool` as disabled. Seven Python tests passed on Windows and on
both Linux server guests. The new runtime test checks immediate lease
installation and disconnect cleanup before the next poll. The patcher
refused a second application without changing files.

```sh
python3 test_agent.py
sudo env GOMAXPROCS=1 go test -p 1 ./device -count=1 -v
```

These commands run in the helper directory and the separately patched
AWG checkout respectively; setup is in the [helper README](flow-confirmation/README.md).
The build used Go 1.25.12 and the same exact pinned revision as v20.

Live lab controls verified kernel lease expiry while A's helper was
stopped, no fresh proof or noise lease from 200 full-ciphertext replays,
and TLS 1.3 rejection without a client certificate. A modified ciphertext
packet spoofing a leased tuple passed A but B rejected it; it did not
refresh the lease. That existing tuple-admission limit remains.

Before shutdown, the lab restored B's original binary, unit and
environment, ordinary DNAT, client NAT and both original profiles. Both
native probes passed. Owned netem/IFB, packet rules, helpers and capture
jobs were removed or stopped; original entry settings were restored.
All four guests, switch and seed server are stopped, with eleven loopback
ports free. Parent disks, earlier reports and personal JSON hashes match.
Production servers, the user's VPN, Windows networking and GitHub were
not changed.

Physical GUI clients, distributed-source noise, candidate-table exhaustion
and production DPI remain outside this study. Keep this candidate in the
lab until the return-gap policy and the CPU exception have separate
acceptance criteria or fixes.
