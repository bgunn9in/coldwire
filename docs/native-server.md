# Native AmneziaWG 3.1: 1 vCPU, 1 GiB RAM

English | [Русский](ru/native-server.md)

The exit runs the official AWG 3.1 userspace implementation under systemd.
One `amneziawg-go` process stays resident and uses Linux's standard TUN
device. Installation adds no Docker/containerd, compiler or AWG kernel module.

## Install from scratch

Supported releases are **Ubuntu 22.04, 24.04 and 26.04 LTS amd64**.
Requirements: a clean server, systemd, Python 3.10+, an assigned
public IPv4, Ubuntu package access and TUN. Copy the whole repository including
`dist`, then run from its root:

```bash
sudo bash servers/install-exit.sh --endpoint NEW_PUBLIC_IPV4 --client windows
```

Replace `NEW_PUBLIC_IPV4` with the **new** VPS address. Default UDP32497 is
overridden with `--port`. Allow that UDP port in the provider firewall without
losing SSH. The installer does not manage external firewall rules. No Amnezia
application, manual key entry or server-side compilation is needed.

To include a profile through an entry server instead:

```bash
sudo bash servers/install-exit.sh --endpoint NEW_PUBLIC_IPV4 --entry ENTRY_PUBLIC_IPV4 --entry-port 32497 --client windows
```

Choose one install command. `--entry` creates alternative profiles only:
**it does not change A**. A's relay must forward to the selected B for that
profile to work. Test direct access to the new B on a spare device first.

For automated coexistence with REALITY, choose `both` in the [wizard](deploy.md).
Standalone AWG installation refuses existing Xray state. Restore AWG first,
then Xray with `--with-awg` for a dual-protocol exit. Running services are not
automatically migrated.

A private VM/LAN endpoint requires an explicit flag:

```bash
sudo bash servers/install-exit.sh --endpoint 10.0.2.15 --allow-private-endpoint --client vm1
```

Only locally assigned RFC1918 10/8, 172.16/12 and 192.168/16 are allowed by
that option. It does not configure upstream NAT or port forwarding: the lab
provides a virtual network separately. Normal mode requires a public address.

## What installation does

Before changing the server, the installer checks the OS, architecture,
systemd, address and port. It refuses an existing deployment, Docker, active
UFW, nftables tables, enabled forwarding, VPN interfaces or conflicting routes
to 10.8.1.0/24. Use a clean VPS if any check fails; disabling networking
on a working server can disconnect its users.

The `dist/awg-native-linux-amd64.tar.gz` checksum must match the pin in code.
Allowed filenames/types, pinned commits and internal hashes are also checked.
The bundle is built on Ubuntu 22.04 amd64 to retain a glibc 2.35 baseline.
The same bundle is used on all three supported LTS releases. Only nftables,
iproute2, kmod and their dependencies are installed on the exit; the standard
tun module is loaded if needed. No general OS upgrade, reboot or SSH change occurs.

`awg genkey/genpsk/pubkey` generates server/client keys, a PSK and a separate
HeaderProtectionKey. AWG 3.1 parameters are Jc=4–6, Jmin=10, Jmax=50;
S1–S4=12; H1–H4=1,2,3,4; ContentPaddingAddition=10–100;
RandomTrailers/DisableCookies=on; randomized timings and a client DNS CPS I1
from upstream constants. Encryption is done by the official implementation,
not by Python.

`awg-relay-kit-exit.service` brings up `awg0`, 10.8.1.1/24, MTU1280 and its
owned **ip awg_exit** forwarding/NAT table. Only 10.8.1.0/24 egress through WAN
and established replies are allowed by its forwarding rules. INPUT/OUTPUT
and SSH are unchanged, and there is no `flush ruleset`. Other VPNs/routing
would require coordination of FORWARD policy on this dedicated VPS.

For a high UDP port systemd grants the Go process only **NET_ADMIN**. An
explicit port below 1024 additionally needs **NET_BIND_SERVICE**. The service
has TUN access, GOMAXPROCS=1 and the soft Go GC goal GOMEMLIMIT=96MiB. This is
not a hard RSS limit; peaks depend on traffic and peer count. The Python
network helper exits after setup instead of remaining a daemon.

## Files and administration

| Path | Purpose |
|---|---|
| `/usr/local/libexec/awg-relay-kit/` | Binaries, manifest, licenses, GPL tool source and startup helper |
| `/etc/awg-relay-kit-exit/server.json` | Private server key, PSK, parameters and peer registry |
| `/etc/awg-relay-kit-exit/awg0.conf` | Persistent AWG configuration |
| `/etc/awg-relay-kit-exit/exit.nft` | Owned forwarding/NAT table only |
| `/etc/systemd/system/awg-relay-kit-exit.service` | Boot-time service |
| `native-runtime.py up/down` | Forwarding on after rules; back to 0 on stop |
| `/root/awg-relay-kit-clients/windows/` | `client.vpn`, `client.conf`, plus `client-via-entry.*` when configured |

Private directories are 0700 and secret files 0600. Private keys and PSKs are
neither printed nor passed in process arguments. Direct and via-entry exports
in one folder are alternatives for **one peer**. Issue new access for another device:

```bash
sudo python3 install_exit.py add-client --name phone
sudo python3 install_exit.py add-client --name mac
```

Adding a peer keeps the server process and existing sessions running.
The next available 10.8.1.2–10.8.1.254 address is used. PSK/HeaderProtectionKey
are server-wide; private client keys differ, following Amnezia's model. Names
are unique, 1–48 letters/digits/`-`/`_`. On issuance failure the old persistent
configuration is restored and partial exports remain private for inspection.
A crash between file writes still requires checking JSON/config/runtime
consistency: this is not a transactional database.

`.vpn` is normal client access without an SSH password or Amnezia administrator
role. `containers`/`amnezia-awg2` are client format identifiers, not a Docker
requirement. The application is needed for client connections; SSH/CLI
administers the server. Automated revocation is not implemented. After a
private backup, consistently remove the peer from `server.json`/`awg0.conf`
and runtime with `sudo /usr/local/libexec/awg-relay-kit/awg set awg0 peer PUBLIC_KEY remove`.

## Verification and troubleshooting

```bash
systemctl status awg-relay-kit-exit.service --no-pager
systemctl is-enabled awg-relay-kit-exit.service
systemctl show awg-relay-kit-exit.service -p MainPID -p MemoryCurrent
sudo /usr/local/libexec/awg-relay-kit/awg show awg0
sudo nft list table ip awg_exit
journalctl -u awg-relay-kit-exit.service -n 40 --no-pager
```

Expect active/running, enabled, a fresh handshake, bidirectional counters,
working websites and the new exit's external IP. For a via-entry client,
B sees A as the peer Endpoint with a possibly different NAT source port.
A direct client appears with its own address. Never publish `showconf`,
`dump`, server.json or client exports: they contain secrets.

`amneziawg-go --version` may show historical 0.0.20250522; use pinned
commits/manifest, support for 3.1 parameters and real traffic as evidence.
The startup banner mentioning kernel support does not prove an AWG kernel
module is installed: this service deliberately uses the userspace binary.
For APT Hash Sum mismatch, inspect mirrors/caches rather than disabling
signature/hash checks. Official HTTPS mirrors helped in the disposable lab.
After foreign nftables changes, restore owned rules using a scheduled service
restart, accounting for interruption of VPN sessions on that exit.

IPv6 egress is not implemented; a client's `::/0` does not create it. Check
IPv6/KillSwitch and client DNS separately. RU lists cover IPv4.

## Backup and restore

```bash
sudo install -d -m 700 /root/private
sudo bash servers/backup-exit.sh /root/private/exit-backup
```

The parent directory must exist, but the output directory must be new.
The backup includes private state, clients and the verified installed bundle.
This lets a restored server make another backup without the original dist
directory. Backup and add-client share a lock; avoid manual edits while
copying. Store the backup encrypted and outside Git. Creating a backup
does not restart the service.

On **another clean Ubuntu VPS** with this repository and a trusted backup:

```bash
sudo bash servers/restore-exit.sh --backup /root/private/exit-backup --endpoint NEW_PUBLIC_IPV4
```

Keys/peers survive; WAN and the new B address are detected again. VM/LAN use
still requires explicit `--allow-private-endpoint`. The backup is not changed.
Old direct exports retain old Endpoints: reconvert `.vpn` using
`--entry NEW_B_IP --port SERVER_PORT` and update `.conf` Endpoint. Existing
profiles through A may remain valid if keys are preserved and A's destination
is updated. New add-client exports use the new B address. OS users/SSH keys
and provider firewall are not transferred.

Reinstallation over existing state is blocked. Failed activation disables the
new service and returns forwarding to 0; no persistent sysctl override is
created. Private files remain for diagnosis, not automatic key reuse. To stop
only this exit: `sudo systemctl disable --now awg-relay-kit-exit.service`.

## Build and full test

The bundle is included. Its build host must remain Ubuntu 22.04 amd64 so
that the resulting binaries retain the oldest supported glibc baseline.
To rebuild, use a **separate** build host:

```bash
sudo bash servers/build-native.sh
```

Existing bundles are not overwritten. Use a separate build checkout without
`dist/awg-native-linux-amd64.tar.gz`, keeping the released copy. Do not rebuild
on a working VPS. Go 1.25.12 is SHA256-checked; upstream commits are pinned.
Only the build machine installs build-essential/git/curl, and temporary Go
is removed. Manifests record provenance and hashes; licenses and GPL tool
source are included. A fresh build may have a different archive hash: after
verifying provenance/content, update `BUNDLE_SHA256` in `install_exit.py`.
Changing only `.sha256` is not a trusted binary update.

An installed disposable private VM can run:

```bash
sudo python3 tests/smoke_native_vm.py --vm-test --client vm1 --second-client vm2 --report /root/vm-report.json
```

It creates temporary namespace clients, adds a second peer, verifies
Internet/NAT and runs ten seconds of TCP load. It requires an owned native
exit with an RFC1918 Endpoint and refuses public addresses. Never run it on
a working production server. [Measurements and reboot/restore results](validation-native.md).

Ubuntu 24.04/26.04 checks and CPU-image requirements: [LTS report](validation-lts.md).
