# Three modes on Ubuntu 22.04 / 1 vCPU / 1 GiB

English | [Русский](ru/validation-protocols.md)

Test date: **9 November 2026**. No changes were made to working external VPS instances, the operator's
VPN or Windows routes. Each mode used fresh
VM disks instead of switching protocols over a prior installation.

## Lab

| Parameter | Value |
|---|---|
| Hypervisor | QEMU / WHPX on Windows, q35, headless |
| Every guest | Official Ubuntu 22.04.5 Minimal Cloud Image amd64 |
| Base image SHA256 | `7ccdeb8161d7993be8c10ba8ab234cb329b947ac59f2882a8a4eccc781a2710c` |
| CPU / RAM per VM | 1 vCPU / 1024 MiB; guest MemTotal 1,008,512 KiB |
| Roles | A relay, B exit, C separate client, D fresh restore exit |
| Network | Private Ethernet between VMs; separate NAT for APT/HTTPS/SSH |
| SSH | Localhost port forwards only; root on A, ordinary user with password sudo on B |
| Passwords | Random with special characters; absent from source/report |

Explicit `--allow-private-endpoint` is used for RFC1918 lab addresses.
Production mode requires assigned public IPv4. Base image: [Ubuntu Jammy
Minimal](https://cloud-images.ubuntu.com/minimal/releases/jammy/release/).
VM network/SSH provisioning are lab prerequisites, not hidden manual VPN setup.

All VMs share one external NAT. Matching ipify output alone cannot establish
B as the exit. Evidence also includes genuine encrypted exchange, a B peer/
socket seeing A, the private client path, independent services and identity
preservation across B's relocation. C uses AWG netns or local Xray SOCKS;
the Windows default route is unchanged.

## Checks

The wizard installs selected services over SSH from scratch, saves direct
and via-entry exports, runs authenticated probes and confirms A. Separate C
then verifies:

- AWG handshake, HTTPS/DNS through the tunnel, direct-route selection for an
  excluded IP and 8 MiB of encrypted traffic.
- REALITY HTTPS via VLESS/Vision, a dual-stack hostname through IPv4, UDP DNS
  inside TCP, refusal of B localhost access and 8 MiB of traffic.
- Wrong UUID/shortId cannot provide Internet egress. Valid access still works
  afterwards. Ordinary TLS to A with target SNI obtains a trusted certificate and h2.
- AWG and REALITY client tests run in parallel in `both`. Each service is
  stopped separately while the other is checked.
- Add a second client, preserve original access, reboot A/B, preserve keys/
  UUID/shortId, then back up and restore to D with a different IP.
- Back up again after restore, exercise A's independent rollback timer and
  direct client fallback to the restored exit.

| Check | AWG | REALITY | Both |
|---|:---:|:---:|:---:|
| Automatic new A/B deployment over SSH | ✓ | ✓ | ✓ |
| Traffic from separate C through A | ✓ | ✓ | ✓, parallel |
| Second client and preserved first client | ✓ | ✓ | ✓ |
| Reboot A/B with preserved identities | ✓ | ✓ | ✓ |
| Backup → new D with changed IP → re-backup | ✓ | ✓ | ✓ |
| Old clients through A after restore | ✓ | ✓ | ✓ |
| Reboot restored D | — | ✓ | ✓ |
| Independent A timer rollback, direct D fallback | ✓ | ✓ | ✓ |
| Works while the other protocol is stopped | — | — | ✓ |

AWG add-client preserved the server PID; Xray add-client restarted Xray only.
Stopping AWG in `both` returned B forwarding to 0 without breaking local Xray
TCP proxying. Restart recovered both protocols. Secret state was compared by
hash instead of printing secrets.

AWG **UDP443** and REALITY **TCP443** on one restored exit also carried
encrypted traffic concurrently. Test D used the fixed AWG unit permitting a
low port; original UDP32497 and its capability set were restored afterwards.

A fresh A was left with its **actual five-minute timer unconfirmed**. Both
protocols worked through A beforehand. At 301.61 seconds after install returned,
forwarding=0 and removal of owned rules/unit were observed. SSH survived and
both direct D fallbacks worked. AccuracySec is explicitly 1 second; lab polling
adds up to three seconds of observation delay.

External DNS/IP-check services occasionally timed out once. DNS checks retry
a lost UDP datagram. REALITY IP verification uses two independent HTTPS
services, like the production probe; persistent failure of both fails the test.
After reboot, the lab waits for DNS and clock synchronization before clients.

## Resources

The measurement is **process RSS**, not complete OS memory. Sampling interval
is 100 ms; the workload is a server-rate-limited 8 MiB transfer, not maximum
throughput. REALITY includes waits for negative tests, so average CPU across
modes is not directly comparable. Go GOMEMLIMIT is a soft GC goal.

| Mode | Process | Before traffic, KiB | Peak sampled RSS, KiB |
|---|---|---:|---:|
| AWG | amneziawg-go | 5680 | 8832 |
| REALITY | Xray | 31552 | 35532 |
| Both | amneziawg-go | 4972 | 8304 |
| Both | Xray | 32252 | 35748 |

The two processes' observed peaks sum to about **43 MiB**, excluding OS,
nftables, page cache and test-fixture memory. A/B had no persistent Docker,
Go SDK or compiler. A uses kernel forwarding and an oneshot service without
a resident proxy process.

`tests/observe_server_vm.py` temporarily serves a bounded HTTP body on a
documentation-range loopback address. This Xray version blocks documentation
networks by default, so **only the guarded VM fixture** adds a narrow freedom
exception for one IP:port during load. Afterwards the original config is
restored and Xray restarted. Production generation has no such exception.
The observer is not an installed VPN component.

## Issues found and fixed

1. Python 3.10 EC_GROUP cannot test X25519 on stock Ubuntu 22.04 OpenSSL.
   Use supported `openssl s_client -groups X25519`, verifying the certificate,
   TLS1.3 and h2.
2. Under umask 077 a newly created `/usr/local/libexec` blocked DynamicUser.
   New executable directories are explicitly 0755; an existing private parent
   is rejected. Secret state/exports remain 0700/0600.
3. systemd 249 rejected `%d` in ExecStart in this environment. LoadCredential's
   path is passed as `${CREDENTIALS_DIRECTORY}/config.json`.
4. IPv6 blocking could reject a whole dual-stack domain. Server DNS and freedom
   sockopt are aligned to `UseIPv4`.
5. In `both`, AWG exports are downloaded immediately after AWG installation,
   before Xray, preserving operator access if a later step fails.
6. Activation/add-client check the ready TCP listener, not just systemctl's
   successful return. Failed client updates restore the previous config.
7. AWG low UDP ports need CAP_NET_BIND_SERVICE. It is added only below 1024;
   high ports retain the original capabilities. Denial without it was reproduced.

Key failure modes are covered by unit tests. Tests also reject a corrupted
bundle even with a replaced `.sha256`, keep the private server key out of
exports and refuse to confirm A if either selected probe fails.

## Application import

Official **AmneziaVPN 5.1.0.6 Linux** was installed in separate C. Installer
SHA256: `f60a4f373332dac8465bd9b8e4f233ee3aa32131fe124d31ca70bc499c73496f`.
The application ran on a virtual X11 display with separate settings for each
test. Its native `--import` saved these in serversList:

- AWG `.vpn`: `amnezia-awg2` container.
- Xray JSON: `amnezia-xray` container.
- VLESS URI: `amnezia-xray` container.

The GUI VPN was not enabled. Native engines in separate VMs verified traffic;
GUI import was a separate format check, not a guarantee for all client/OS
versions. Physical Windows/macOS/Android/iOS connections were not switched.

## Reproduction and boundaries

Prepare isolated A/B/C with private IPs, deploy a mode and copy test exports
to C. `tests/smoke_clients_vm.py --help` documents --vm-test, --protocol,
--entry, --profiles, --bin, --reference-file and --report. `--bin` contains
verified client binaries; reference-file is B's HTTPS ipify response. AWG on C
needs iproute2/nftables/TUN. For load, start the observer on B, wait for
`/root/kit-observer.ready`, then stop it with SIGTERM after the client so it
saves metrics and removes the fixture. `--quick` needs no observer and skips
load/negative checks.

Both test scripts require root and an RFC1918 endpoint. Never run them on
working production servers. Full runs need virtual-network preparation;
these are not production diagnostic commands.

**44/44 unit tests** passed on Windows, along with Python compilation and
PowerShell syntax. Bash scripts were checked in Ubuntu. Windows
`setup.ps1 --help` and `setup.sh --help` inside a fresh Ubuntu venv installed
dependencies and forwarded arguments to the wizard. Offline generation
reproduced both JSON files with [documented hashes](lists.md). Local links
and nested archives were checked for real credentials, node addresses and
personal local paths.

These checks do not establish multi-day stability, arbitrary client counts,
VPS throughput limits, target reachability everywhere, DPI evasion or resistance
to correlation. IPv6 egress, all DoH/KillSwitch combinations and every provider
firewall were not tested. This report covers Ubuntu 22.04 amd64; see the
[later LTS checks](validation-lts.md) for Ubuntu 24.04 and 26.04.
