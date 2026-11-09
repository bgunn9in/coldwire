# Debian 12 and 13 verification

English | [Русский](ru/validation-debian.md)

Test date: **10 November 2026**. AWG, REALITY and both protocols were installed
from scratch on Debian 12 and 13. Each of the six cases used new A/B/C disks:
A was the relay, B the exit and C a separate client. D was a new exit for
restore. Every guest had **1 vCPU and 1024 MiB RAM**. Working external servers,
the operator's VPN and Windows routes were unchanged.

## Platform changes

The shared Python host check and both shell host checks now accept Debian
12/13 alongside Ubuntu 22.04/24.04/26.04 LTS. Other releases, derivatives
identified only by `ID_LIKE`, non-amd64 hosts and hosts without systemd remain
unsupported. Checks for existing installations, firewall rules, SSH identity
and binary bundles remain in place.

The AWG and Xray binaries, service units and protocol settings are unchanged.
Debian uses the supplied bundles. Rebuilding AWG still requires a separate
Ubuntu 22.04 amd64 machine to retain the glibc 2.35 baseline.

The [Debian 13 release notes](https://www.debian.org/releases/trixie/release-notes/whats-new.html)
describe its Python 3.13 and OpenSSL 3.5 updates. The tests exercised those
versions as well as Debian 12's Python 3.11 and OpenSSL 3.0.

| Debian | Kernel | Python | systemd | OpenSSL | glibc |
|---|---|---|---|---|---|
| 12 | 6.1.0-54-cloud-amd64 | 3.11.2 | 252 | 3.0.22 | 2.36 |
| 13 | 6.12.115+deb13.1-cloud-amd64 | 3.13.5 | 257 | 3.5.7 | 2.41 |

## Images and lab

The official genericcloud amd64 images came from the
[Bookworm directory](https://cloud.debian.org/images/cloud/bookworm/latest/)
and [Trixie directory](https://cloud.debian.org/images/cloud/trixie/latest/).
Their SHA512 hashes matched the corresponding SHA512SUMS retrieved over
HTTPS. GPG signatures were not independently checked. The URLs can later
point to newer images.

| Image | Downloaded SHA256 |
|---|---|
| debian-12-genericcloud-amd64.qcow2 | 24036a8b79cbb11d809752c60f2f885b1a3b02b1d663faa0b648eb87bd7a256e |
| debian-13-genericcloud-amd64.qcow2 | de9d63f5e5ec5927d7548bc05b6043b87457b8c1cb9bcb95365168e8d0293b4f |

QEMU/WHPX ran natively on Windows, using the locally patched QEMU 11.1.3
build from the [ordinary-reboot investigation](validation-lts.md#ordinary-reboots).
WSL2 was not used. Guests shared a private Ethernet network and had separate
NAT access for packages, Internet traffic and localhost SSH port forwards.
A used root/password SSH; B used a normal account with password sudo.
No Docker, containerd, Go SDK or compiler was installed on A/B.

The Debian 13 case with both protocols used `qemu64` without AVX/AVX2;
other cases used `max`. Preparing SSH and the private test LAN was separate from VPN
installation. The wizard installed the VPN over SSH using the supplied
server addresses, ports, logins and passwords.

## Results

| Debian | Mode | SSH install | HTTPS/DNS via A | Instrumented A/B reboots | Restore and rebackup | Direct fallback |
|---|---|---|---|---:|---|---|
| 12 | awg | PASS | PASS | 4 | PASS | PASS |
| 12 | reality | PASS | PASS | 4 | PASS | PASS |
| 12 | both | PASS | PASS | 4 | PASS | PASS |
| 13 | awg | PASS | PASS | 4 | PASS | PASS |
| 13 | reality | PASS | PASS | 4 | PASS | PASS |
| 13 | both | PASS | PASS | 4 | PASS | PASS |

For the selected protocols, the checks also covered:

- An 8 MiB encrypted transfer and a separate client whose exit matched B.
  AWG additionally selected a direct route for an excluded address.
- REALITY rejected wrong UUIDs and shortIds, blocked B's local SSH port
  and returned a valid target certificate and h2 to an ordinary TLS request.
- A new client worked alongside the original. AWG kept its server PID;
  adding an Xray client restarted only Xray.
- With both protocols installed, traffic tests ran concurrently. Each
  protocol worked while the other service was stopped.
- Original identities survived reboots, backup and restore to D at a
  different private IP. After updating A's destination, both saved clients
  still worked. D rebooted and made another backup.
- A three-second independent test timer invoked rollback. SSH survived,
  forwarding returned to its saved value and direct access to D worked.

The final ordinary-reboot matrix issued four guest commands per case: A alone,
B alone, then A/B back-to-back. All **24** passed with new Linux boot IDs,
guest-originated QMP RESET events, unchanged Windows QEMU PIDs and process
creation times, and a continuous QMP connection. Enabled services, owned
rules, identities and client traffic were checked after each phase.
No cold-start fallback or manual service restart was used.

All guests shared the host's external NAT. Matching an external-IP response
alone would not prove the path; the tests also checked the configured entry,
authenticated protocol traffic, A's source address at B and relay rules.

The real five-minute timer was armed and confirmed in every deployment.
Its full expiry was checked separately with both protocols on each Debian:

| Debian | Seconds observed after installer return | Rules removed, SSH and direct fallbacks work |
|---|---:|---|
| 12 | 303.15 | PASS |
| 13 | 302.51 | PASS |

Timer accuracy was set to 1 second; three-second polling adds observation delay.

## Process memory

Values are idle / observed peak RSS in MiB, excluding the OS and test
fixtures. The load was a short, rate-controlled 8 MiB transfer. These
measurements do not establish maximum throughput or capacity.

| Debian | Mode | AWG MiB | Xray MiB |
|---|---|---:|---:|
| 12 | awg | 15.02 / 19.00 | - |
| 12 | reality | - | 31.70 / 37.62 |
| 12 | both | 13.16 / 14.65 | 33.68 / 37.82 |
| 13 | awg | 17.89 / 22.93 | - |
| 13 | reality | - | 33.55 / 38.41 |
| 13 | both | 17.77 / 20.47 | 31.90 / 38.27 |

## Automated checks and reproduction

All **48/48 unit tests** passed on Windows, Debian 12/Python 3.11 and
Debian 13/Python 3.13, without skips. On both Debian versions, `setup.sh`
created a fresh venv, installed pinned Paramiko and forwarded wizard
arguments. Bash syntax checks passed.

Windows validation also exposed a launcher problem: `py -3` selected
experimental Python `3.13t`. The [Python Windows guide](https://docs.python.org/3/using/windows.html)
documents this preference. The launcher now selects a standard registered
minor version explicitly and refuses unsupported existing venvs before pip.
A fresh standard CPython 3.13.5 venv installed Paramiko 5.1.0 and passed
all 48 tests.

Separate mount-namespace checks ran both real shell host gates against
five supported and eight unsupported or incomplete OS descriptions:
**26 checks passed**. They exercised read-only preflight; no server
installation ran under a substituted OS identity.

For unit tests on a Debian operator machine, start from the source root.
Standard CPython 3.10+ with venv/pip must already be installed:

```bash
bash setup.sh --help
.venv/bin/python -m unittest discover -s tests -v
```

The network scenarios are in [smoke_clients_vm.py](../tests/smoke_clients_vm.py) and
[observe_server_vm.py](../tests/observe_server_vm.py). Prepare isolated A/B/C
guests with private addresses, deploy through the wizard with the explicit lab flag, and place
issued profiles and verified client binaries on C. The
[protocol report](validation-protocols.md#reproduction-and-boundaries)
documents the observer and client arguments. These privileged scenarios
are for disposable VMs and refuse public endpoints.

## Test fixes and limits

The HTTP seed used `nocloud-net` on Debian 12 and `nocloud` on Debian 13,
matching their cloud-init versions. The first reboot check also returned
from SSH before Linux had restarted. Its wait now requires a changed boot ID and retries short
SSH/IPv4-DNS timeouts within a bounded interval. The affected reboot
checks were rerun successfully.

One HTTPS request to example.com timed out after a restore. A direct
request from D and subsequent client checks passed without changing VPN
configuration. External site availability remains a test dependency.
These test failures did not require a change to VPN services or protocol settings.

Each case used the same Debian major release on A/B/C/D. Mixed-distribution
pairs, in-place OS upgrades, physical client GUIs, every provider firewall,
all DNS/DoH/KillSwitch combinations, multi-day traffic and DPI evasion were
not tested. IPv6 egress is not implemented. The full Ubuntu VM cycles were
not repeated for this allowlist change; their earlier results are in the
[Ubuntu LTS report](validation-lts.md).
