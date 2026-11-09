# Full native-exit verification in Ubuntu VMs

English | [Русский](ru/validation-native.md)

On **9 November 2026**, the complete installer was tested from scratch:
APT, bundled binaries, systemd, real AWG keys, interface and NAT. Working
external VPS instances were not used for installation or diagnosis.

## Lab

| Parameter | Value |
|---|---|
| Virtualization | QEMU 11.1.0 development build, WHPX, Windows host |
| Guest OS | Official Ubuntu 22.04.5 LTS Minimal Cloud Image amd64 |
| Base disk SHA256 | `7ccdeb8161d7993be8c10ba8ab234cb329b947ac59f2882a8a4eccc781a2710c` |
| Source | `https://cloud-images.ubuntu.com/minimal/releases/jammy/release/ubuntu-22.04-minimal-cloudimg-amd64.img` |
| Kernel | 5.15.0-1112-kvm |
| Exit / restore VM | **1 vCPU**, 1024 MiB each; Linux MemTotal 1,008,512 KiB |
| Network | QEMU user networking, private IPv4; Windows adapters/routes unchanged |
| Address option | Explicit `--allow-private-endpoint`, VM address 10.0.2.15 |
| Build VM | Separate Ubuntu 22.04 amd64, 2 vCPU / 2 GiB; compilers not copied to exits |
| Bundle | 1,671,834 bytes; SHA256 `44c066267291dcfbf493725f00d28ce65fd7722097a434927efa18c9e3b90749` |

New qcow2 overlays were created over the verified base disk. After fixes, the
final cycle used **fresh overlays again**, not existing installations.
Docker, Go compiler and build tools were absent on exit VMs before and after.

An Ubuntu HTTP mirror once returned a Hash Sum mismatch. The lab switched
standard archive.ubuntu.com/security.ubuntu.com mirrors to HTTPS without
disabling APT signatures/hashes. This changed transport only in disposable
VMs, not working servers or Windows.

## Tested cycle

1. One-command installation on a clean VM: APT installs nftables/iproute2/kmod;
   the installer verifies the bundle, generates keys, first peer and systemd service.
2. Verify active/running and enabled, no Docker/Go toolchain, an AWG UDP
   listener and private exports.
3. Use a real client in a separate Linux network namespace: supply generated
   `.conf` to official `awg`, start userspace AWG, exchange TCP with 10.8.1.1
   and perform Internet HTTPS through the tunnel/NAT. Client DNS to
   1.1.1.1/1.0.0.1 also crosses the tunnel. Python is the test application;
   actual AWG processes encrypt both ends.
4. Add a second peer without changing the server PID; both first and second
   clients retain Internet connectivity.
5. Transfer TCP for ten seconds through the encrypted tunnel, sampling server
   process RSS/CPU every 100 ms. No iperf or Docker is installed on the exit.
6. Reboot **guest Ubuntu**, verify changed boot_id, automatic AWG startup and
   preserved SHA256 of server.json, awg0.conf and both `.vpn` files. Network
   checks pass again after reboot.
7. Repeated install refuses existing state while preserving configuration
   and working clients.
8. Create a private backup without stopping service, restore to a fresh
   1 vCPU / 1 GiB VM, verify byte-identical server config and fresh handshakes/
   Internet for both clients.
9. Back up the restored exit **without the original dist directory**, using
   its verified installed bundle.
10. At this native-exit stage **24/24** unit tests passed on Windows and
    Ubuntu. Bash syntax and Python compilation passed.
11. Stop/start on original and restored VMs removes the owned nft table/TUN
    and returns forwarding to 0. Startup restores forwarding=1 without key
    changes or duplicated nft rules. Modes 0700/0600 were checked. Lab
    sources were compared with that stage's code using Python AST.

`tests/smoke_native_vm.py` contains a repeatable network scenario. It requires
root in a disposable VM with a private Endpoint and explicit `--vm-test`.
It creates/removes namespaces and adds a test peer. Lab SSH/VPN keys and VM
images are not in Git.

## Final-cycle measurements

| Stage | RSS before traffic | Peak sampled RSS | TCP | Server process CPU |
|---|---:|---:|---:|---:|
| Clean install | 4796 KiB | 24,788 KiB | 70.21 Mbit/s | 36.30% |
| After reboot | 4324 KiB | 22,376 KiB | 64.14 Mbit/s | 35.76% |
| Restored VM | 4988 KiB | 26,948 KiB | 67.48 Mbit/s | 33.94% |

Immediately after startup systemd MemoryCurrent was about 2.6 MiB and RSS
4–5 MiB. They account for shared pages differently. Loaded process RSS was
about 22–27 MiB, reaching 28–29 MiB in earlier runs. GOMEMLIMIT=96MiB is a soft
GC goal, not a promise of matching RSS or a hard limit for any client count.

The server, both clients and test application **shared one VM vCPU**. TCP
results are functional measurements, not a real VPS/provider speed limit or
guarantee. Hundreds of clients, multi-day traffic and DPI were not tested.

## Issues found and fixed

- The native CLI gained an executable entry point. Successful exit status
  alone is not deployment evidence; active service and real traffic are checked.
- Minimal Ubuntu's missing `ping` is no longer a test dependency; use a
  verified TCP response and real HTTPS.
- Forwarding follows service lifecycle without an unnecessary permanent
  override: enable after owned rules and return to 0 on stop.
- Failed activation disables service and restores forwarding. Private
  files remain for diagnosis and block installation over partial state.
- Backup uses the installed bundle and works after restore without original
  dist. Lock acquisition precedes reading state.
- Bundle hashes/member allowlists are checked first; corruption, traversal
  filenames, implicit private endpoints and multicast addresses are rejected.

## Boundaries

This cycle tested Ubuntu **22.04**. The later [LTS report](validation-lts.md)
covers 24.04 and 26.04. glibc compatibility alone does not validate an
installation. These measurements belong to this cycle and were not repeated
for every later code change.
New `.vpn` schema/encode-decode were checked; these exact new exports were
not imported separately on physical Windows/macOS/Android/iOS at this stage.
Native `.conf` carried actual traffic. IPv6 egress and all physical-client
DNS variants were not tested. Working external VPS instances were excluded.

## Generic toolkit verification

The anonymized revision prepared on 9 November 2026 passed **33/33 unit tests**
on Windows, including mandatory converter entry address, optional protected
list-generation IPs and refusal of untested OS releases. Bash syntax, Python
compilation, local Markdown links, list hashes/counts and offline JSON
reproduction were checked. The full VM install/reboot/restore cycle was not
rerun for that editorial change; network results above belong to the stated lab.

After REALITY was added, a new three-mode cycle was completed.
[Ubuntu 22.04 results and limitations](validation-protocols.md).
