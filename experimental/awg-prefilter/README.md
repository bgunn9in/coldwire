# AWG Header Protection + MAC1 prefilter

English | [Русский](README.ru.md)

This is a lab prototype for COLDWIRE's entry relay. It checks AWG headers
before forwarding packets to the exit. Existing AWG 3.1 clients keep their
profiles and need no extra software. The normal installers do not enable it.

The prototype uses one C process, OpenSSL 3 and nftables NFQUEUE. The entry
receives the HeaderProtectionKey and the exit's public key. It does not
receive the exit's VPN private key, client private keys, PSK or session keys.
User traffic remains encrypted between client and exit.

## What it checks

For incoming IPv4/UDP packets selected by the example rules, the process:

1. Checks IP/UDP lengths and reads the 12-byte AWG prefix as the ChaCha20 nonce.
2. Decodes the message type using HeaderProtectionKey.
3. For initiation and response messages, decrypts the protected handshake
   fields and checks MAC1 with keyed BLAKE2s-128. Random trailers are excluded.
4. Accepts recognized transport and cookie messages with sufficient length.
   The exit performs their authentication. Rejected packets receive no reply
   from the filter. Accepted packet contents are unchanged.

Only **S1-S4=12 and H1-H4=1,2,3,4** are supported. These are COLDWIRE's current
defaults. IPv6 outer transport and other parameter combinations are outside
this prototype. The parser supports IPv4 options; Linux handles defragmentation
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

It prints `ready` after binding the queue. SIGUSR1 prints cumulative JSON
counters; SIGTERM prints the final counters and closes the queue. There are
no per-packet logs. Queue length is bounded at 2048; fail-open is disabled.
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

## Measurements

See the [VM report](validation.md) and [machine-readable results](results.json).
The report separates client interoperability, malformed traffic, flow-table
pressure and throughput. Its scope is the tested Linux client core; physical
Windows/macOS/Android/iOS GUI clients were not operated in these tests.
