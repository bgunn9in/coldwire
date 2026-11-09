# Ubuntu 24.04 and 26.04 LTS verification

English | [Русский](ru/validation-lts.md)

Test date: **9 November 2026**. Each of the three modes was installed on fresh
Ubuntu 24.04 and 26.04 VM disks. No changes were made to working external
servers, the operator's VPN or Windows routes. The earlier [Ubuntu 22.04
report](validation-protocols.md) remains a separate test cycle.

## What changed

The SSH preflight, manual relay installer and both exit installers now accept
Ubuntu **22.04, 24.04 and 26.04 LTS amd64**. AWG and Xray share the Python host
check. Other OS releases and architectures are rejected before installation.
Existing-installation, firewall, host-key and bundle checks remain in place.

The released binaries and protocol settings are unchanged. AWG's build script
still requires a separate Ubuntu 22.04 amd64 build host to retain the glibc
2.35 baseline. Installing or restoring on 24.04/26.04 does not require a rebuild,
Docker or a compiler.

## Platform research

Ubuntu 26.04 uses sudo-rs and rust-coreutils by default; cp, mv and rm still
use GNU implementations. The installer worked with the supplied utilities
and password sudo, without replacing them. See the [official 26.04 LTS
changes](https://documentation.ubuntu.com/release-notes/26.04/summary-for-lts-users/).
The [24.04 release notes](https://documentation.ubuntu.com/release-notes/24.04/)
were also reviewed.

amd64v3 images require the corresponding CPU features. The 26.04 AWG-only
and REALITY-only runs used amd64v3; the dual-protocol run used the standard
amd64 image and QEMU's qemu64 CPU model, with no AVX/AVX2 advertised to the guest.
Choose an image compatible with the virtual CPU your VPS provider exposes.
[Ubuntu cloud architecture variants](https://ubuntu.com/cloud/public-cloud/docs/all-clouds-explanation/architecture-variants/).

## Lab

QEMU/WHPX on Windows ran four roles: A relay, B exit, C separate client and
D fresh restore exit. Every guest had **1 vCPU and 1024 MiB RAM**, with private
Ethernet between guests and separate NAT for packages/Internet access. SSH used
localhost port forwards only. A used root/password; B used an ordinary account
with password sudo. Random passwords included shell metacharacters.

| Measured guest | Kernel | Python | systemd | sudo | nftables on AWG B |
|---|---|---|---|---|---|
| 24.04.5 | 6.8.0-147-generic | 3.12.3 | 255 | 1.9.15p5 | 1.0.9 |
| 26.04.1 | 7.0.0-42-generic | 3.14.4 | 259 | sudo-rs 0.2.13 | 1.1.6 |

Base images came from [Ubuntu Noble Minimal](https://cloud-images.ubuntu.com/minimal/releases/noble/release/)
and [Ubuntu Resolute Minimal](https://cloud-images.ubuntu.com/minimal/releases/resolute/release/).
Their hashes matched SHA256SUMS retrieved over HTTPS. GPG signatures were not
independently checked. These release URLs can later point to newer images.

| Image | Filename | Downloaded SHA256 |
|---|---|---|
| 24.04 | `ubuntu-24.04-minimal-cloudimg-amd64.img` | `406630c08b5e545fcc7209854b129d47e3af822db128c9f19336593b5a2d3fe0` |
| 26.04 | `ubuntu-26.04-minimal-cloudimg-amd64v3.img` | `6c4af12c035a79b7c83dde748820ea727e33f7100b5e8e56c469bce9f37f1309` |
| 26.04-amd64 | `ubuntu-26.04-minimal-cloudimg-amd64.img` | `ee808a4ad9e4bab636cec268e1b6385115e756be45ee30d7b3df84b832908ddc` |

The lab switched the official APT mirrors from HTTP to HTTPS without disabling
package signature/hash checks. That change affected disposable VMs only.

## Results

All six combinations passed:

- Fully automated SSH deployment, authenticated probes through A and confirmation
  of A's rollback timer. B observed A as the peer/socket source.
- A separate client sent HTTPS and DNS through the selected protocol, matched
  the exit reference and transferred 8 MiB of encrypted test traffic.
- REALITY rejected incorrect UUID/shortId, blocked private destinations and
  served a valid target certificate to an ordinary TLS request.
- Adding a second client preserved original access. AWG kept its process;
  Xray restarted only its own service.
- A/B started from their saved disks with new boot IDs; keys and both clients
  remained valid. D restored a private backup at a different lab address,
  started from disk again and produced another backup.
- An independent three-second test timer invoked the rollback script. A's
  forwarding returned to its saved value, and direct access to restored D worked.
- In each `both` run, either protocol worked while the other service was stopped.
  Docker, containerd, Go and GCC were absent from the exit's executable path.

`setup.sh --help` created a new venv and installed pinned Paramiko on Python
3.12 and 3.14. All **47/47 unit tests** passed on both guest Python versions and
Windows, without skips. Bash syntax and Windows launcher syntax passed. The
unit tests reproduced both RU JSON files offline with their documented hashes.

## Process memory

Values are idle / observed peak RSS in MiB. The load was a short, rate-controlled
8 MiB transfer, not a maximum-throughput benchmark. Columns measure individual
VPN processes, excluding the OS and test fixtures; observation times differ.

| Guest | Mode | AWG MiB | Xray MiB |
|---|---|---:|---:|
| 24.04 amd64 | `awg` | 5.82 / 7.70 | - |
| 24.04 amd64 | `reality` | - | 30.61 / 35.91 |
| 24.04 amd64 | `both` | 5.47 / 7.76 | 30.64 / 35.93 |
| 26.04 amd64v3 | `awg` | 5.57 / 8.15 | - |
| 26.04 amd64v3 | `reality` | - | 37.72 / 41.63 |
| 26.04 amd64 | `both` | 5.60 / 8.26 | 38.02 / 41.70 |

## Test limits and failures

QEMU/WHPX failed with an xsave error during a soft reset of a 24.04 guest.
The remaining persistence checks used clean guest shutdown followed by a new
QEMU process on the same disk. They verify cold-boot autostart and saved state;
they do not verify a successful WHPX soft reset on these new OS releases.

One initial REALITY/26.04 run timed out at both external HTTPS address checks.
A quick check and a complete rerun then passed without a runtime-code or
configuration change. External service availability remains a test dependency.

The real five-minute timer was armed and confirmed during deployment. Its full
expiry was not repeated on 24.04/26.04; the [22.04 report](validation-protocols.md)
records that test. The three-second timer here exercised the rollback script.

These runs do not establish multi-day stability, maximum client counts or DPI
evasion. IPv6 egress is not implemented. Physical client applications, every
provider firewall and all DNS/DoH/KillSwitch combinations were not retested.
In-place distribution upgrades were not tested; installers require clean hosts.
