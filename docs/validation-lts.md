# Ubuntu 24.04 and 26.04 LTS verification

English | [Русский](ru/validation-lts.md)

Test date: **9 November 2026**. Each of the three modes was installed on fresh
Ubuntu 24.04 and 26.04 VM disks. No changes were made to working external
servers, the operator's VPN or Windows routes. The earlier [Ubuntu 22.04
report](validation-protocols.md) remains a separate test cycle.

Ordinary A/B reboots passed in the [10 November follow-up](#ordinary-reboots)
using a locally patched QEMU/WHPX test build.

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
those initial checks did not verify a successful WHPX soft reset. The
[10 November follow-up](#ordinary-reboots) below verifies ordinary reboots
using a locally patched test-tool build.

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

## Ordinary reboots

Follow-up date: **10 November 2026**. All six OS/protocol combinations now pass
ordinary `sudo -n systemctl reboot` on A and B. Each case used fresh VM disks,
1 vCPU and 1024 MiB per guest, plus a separate client C. The VPN scripts and
released bundles are byte-for-byte unchanged from the initial LTS checks.
Working external servers, the operator's VPN and Windows routes were unchanged.

### WHPX diagnosis and local repair

These are native Windows QEMU processes with `-accel whpx`, not WSL2 guests.
The host is Windows 11 build 26300. The original installed QEMU reports
`11.1.0 (v11.1.0-12130-ge470268ff4)`. The failure also occurs on a relay with no
VPN service running: Linux reaches its reboot target, then QEMU fails to boot
the guest again.

The following controls used the same Ubuntu 24.04 disk. A failed control did
not return with a new boot ID within 75 seconds; its serial/QMP logs were saved.

| QEMU | CPU | Interrupt controller | Firmware | Result |
|---|---|---|---|---|
| Installed 11.1.0 build | `max` | Default | SeaBIOS | Failed |
| Installed 11.1.0 build | `max` | `kernel-irqchip=off` | SeaBIOS | Failed |
| Installed 11.1.0 build | `qemu64` | Default | SeaBIOS | Failed |
| Installed 11.1.0 build | `qemu64` | `kernel-irqchip=off` | SeaBIOS | Failed |
| Installed 11.1.0 build | `max` | Default | UEFI | Failed |
| Locally built 11.1.3, unmodified | `max` | Default | SeaBIOS | Failed |
| Same 11.1.3 build with partition-reset patch | `max` | Default | SeaBIOS | Passed, 15.74 seconds to new boot ID |

The successful build applies the [proposed upstream WHPX partition-reset
patch](https://patchew.org/QEMU/20260421205749.55060-1-mohamed@unpredictable.fr/).
It adds a reset callback calling `WHvResetPartition` while guest CPUs are
stopped, before QEMU writes their reset state. The same-version control
localizes the failure to this reset path on the tested host; changing VPN
settings was unnecessary.

Microsoft documents that [WHvResetPartition](https://learn.microsoft.com/en-us/virtualization/api/hypervisor-platform/funcs/whvresetpartition)
reinitializes virtual processors and pending per-processor state, while
preserving mapped guest memory. The function is available on this host.
This is a local test-tool build using a proposed patch, not a claim that
released QEMU 11.1.3 contains the fix. No QEMU binary is distributed by COLDWIRE.
Ubuntu VPS installations do not need QEMU, MSYS2 or this patch.

The source is the official QEMU 11.1.3 tarball; its PGP signature was checked
against the release key fingerprint published on the [QEMU download page](https://www.qemu.org/download/):
`CEACC9E15534EBABB82D3FA03353C9CEF108B584`.
It was built separately with portable MSYS2 UCRT64, GCC 16.2.0, WHPX enabled
and TCG disabled. The installed system QEMU and Windows settings were unchanged.
The patched and unpatched builds used the same 51 bundled DLLs and installed
firmware.

| Local build input/output | SHA256 |
|---|---|
| Official source tarball | `5a8289c7940dc77d3873c81a6c29ba3afe1446fc9d36e77fa1658cdbecb84b22` |
| Applied patch, normalized LF and final newline | `aa659609ea554908252d8e609aa87147c330454827c742109fe6da172cd1db5b` |
| Tested patched executable | `2fe0a473a1071cf0a776a61b657677aa21b3813b03f16676e4b390ecd10e6edc` |

### Reboot verification

For each case, the test first verified client traffic, then rebooted A alone,
B alone, and A/B back-to-back without waiting for A to return. This is four
guest reboot commands per case, **24 in total**. After every phase it checked:

- A new Linux `boot_id` and a guest-originated QMP `RESET` event.
- The same Windows QEMU PID and process creation time, with the QMP connection
  kept open throughout. No process restart or cold-start fallback was used.
- Enabled/active services, forwarding and owned nftables rules. No manual
  service restart was performed to make a post-reboot check pass.
- Unchanged VPN identities and successful HTTPS, external-IP and DNS checks
  from C through A. `both` checked AWG and REALITY concurrently.

| Ubuntu | Mode | A alone | B alone | A/B together | Guest reboots |
|---|---|---|---|---|---:|
| 24.04 | `awg` | PASS | PASS | PASS | 4 |
| 24.04 | `reality` | PASS | PASS | PASS | 4 |
| 24.04 | `both` | PASS | PASS | PASS | 4 |
| 26.04 | `awg` | PASS | PASS | PASS | 4 |
| 26.04 | `reality` | PASS | PASS | PASS | 4 |
| 26.04 | `both` | PASS | PASS | PASS | 4 |

All guests share the host's external NAT, so matching the external IP alone
is insufficient evidence. The probes also check the configured entry path,
actual authenticated traffic and persistent relay rules.

The full matrix used default WHPX interrupt handling and SeaBIOS. CPU/image
selection matched the earlier tests: 24.04 and the 26.04 single-protocol cases
used `max`; the 26.04 dual-protocol case used `qemu64` and the standard amd64
image. No guest kernel reboot parameters were changed.

### Remaining limits

The backend still sometimes logs `failed to get xsave state` and an ignored
interrupt-vector warning. They also appear in successful reboot checks; this
follow-up does not claim to fix every WHPX diagnostic or CPU save/restore path.
The [QEMU XSAVE diagnostic](https://github.com/qemu/qemu/blob/v11.1.3/target/i386/whpx/whpx-all.c)
uses C `errno` when reporting a Windows API failure, so its displayed suffix
alone does not identify the underlying HRESULT.

The successful result applies to this local patched QEMU/Windows combination.
Migration and long-running hypervisor workloads were not validated. The
restored exit D was not part of this ordinary-reboot matrix. The earlier load,
restore and five-minute-timer boundaries still apply.
