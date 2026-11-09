# Servers: relay and native exit deployment

[Русский](../servers.md) · **English**

**Ubuntu 22.04** is supported; the lab used amd64. Other Ubuntu versions are
untested and rejected. The native exit binary bundles are amd64 only.

A is the nftables entry relay; B runs AWG 3.1 and/or Xray REALITY under
systemd. Clients send encrypted traffic to A. DNAT changes its destination to
B and SNAT/masquerade makes replies return through A. Decryption happens on
B. A holds no VPN keys and runs no persistent userspace tunnel process.

Replace `ENTRY_IPV4`/`EXIT_IPV4` with your own addresses. To deploy both servers
automatically, use [deploy](deploy.md). The following is the manual alternative
from a complete repository copy.

## Exit B

AWG requires clean Ubuntu 22.04 amd64 with systemd, Python 3.10+, TUN and an
assigned IPv4. No Docker or Go compiler is installed on the exit.

```bash
sudo bash servers/install-exit.sh --endpoint EXIT_IPV4 --entry ENTRY_IPV4 --client client1
```

Exports are placed in `/root/awg-relay-kit-clients/client1/`. Test the direct
profile first. `--entry` creates alternative exports but does not configure A.
[Native AWG details](native-server.md).

For REALITY see [its guide](xray.md). For both protocols use the wizard, which
coordinates checks and installation order.

## Entry A

A's IPv4 must be assigned to the external interface, and the route to B must
use that interface. Requirements: root, Python 3, iproute2/ss, systemd and APT
access. Before installation forwarding must be 0, nftables must have no
tables, and UFW must be inactive. Running containers or an existing relay
cause refusal. Additional provider-side NAT is unsupported.

```bash
sudo bash servers/install-entry.sh ENTRY_IPV4 EXIT_IPV4
# Optional: different input and destination UDP ports:
# sudo bash servers/install-entry.sh ENTRY_IPV4 EXIT_IPV4 443,32497 32497
# REALITY TCP443 only:
# sudo bash servers/install-entry.sh ENTRY_IPV4 EXIT_IPV4 - 32497 443 443
# Both: AWG UDP32497 and REALITY TCP443:
# sudo bash servers/install-entry.sh ENTRY_IPV4 EXIT_IPV4 32497 32497 443 443
```

By default, **one UDP entry port 32497** forwards to B:32497. The provider
firewall must allow selected incoming ports and outbound TCP/UDP to B. The
installer does not manage that firewall. The fifth argument selects the TCP
entry port (0 disables TCP), the sixth B's TCP port. `-` as the third argument
disables UDP. TCP and UDP with the same number are distinct ports.

The owned `ip blackice_relay` table contains DNAT, masquerade only for DNAT
connections, and a drop-policy FORWARD chain permitting selected flows and
replies. TCP selection adds analogous REALITY forwarding rules. INPUT/OUTPUT
and SSH are unchanged; there is no `flush ruleset`. Use a dedicated relay:
other routed VPNs/networks require coordinated FORWARD policy. No listener
on A is required in `ss -lunp` or the TCP equivalent, because forwarding runs
in the kernel without a listening TCP/UDP socket.

## Verify and confirm A

Before enabling the relay, an independent **five-minute** systemd timer is
armed. Test via A on a separate device with separate access: websites work
and external IPv4 equals B. Then run on A:

```bash
sudo bash /var/lib/awg-relay-kit/confirm-entry.sh
systemctl is-active blackice-relay.service
systemctl is-enabled blackice-relay.service
systemctl is-active blackice-relay-safety.timer
```

After confirmation, the relay is active/enabled and the timer inactive.
Deploy confirms automatically after authenticated server-side probes, which
do not replace a separate device-network check.

If verification fails, wait for the timer or invoke:

```bash
sudo bash /var/lib/awg-relay-kit/rollback-entry.sh
```

Only relay files/table are removed and the previous forwarding value is
restored; B is untouched. `/var/lib/awg-relay-kit` remains for diagnosis and
blocks installation over retained state. Rollback disconnects clients through
A; save a direct B profile first.

The transient timer **does not survive reboot**. Do not reboot A before
confirmation. Once confirmed, the relay starts at boot through systemd.

| Path on A | Purpose |
|---|---|
| `/etc/blackice-relay.nft` | Owned rules |
| `/etc/systemd/system/blackice-relay.service` | Relay service |
| `/etc/sysctl.d/90-blackice-relay.conf` | Persistent IPv4 forwarding |
| `/var/lib/awg-relay-kit/` | Confirmation, rollback and saved state |

Do not reapply `nft -f` over an existing table: it may duplicate rules.
Changes to a running relay need a private rules backup and rollback plan.

## Exit backup/restore

```bash
sudo install -d -m 700 /root/private
sudo bash servers/backup-exit.sh /root/private/exit-backup
# On a different clean B:
sudo bash servers/restore-exit.sh --backup /root/private/exit-backup --endpoint EXIT_IPV4
```

Backups contain secrets and belong outside Git. Restore preserves VPN keys
and peers, not OS users/SSH keys or the external firewall. If B changes,
update direct profile Endpoints and A's destination separately. Servers
installed by the Amnezia application or Docker are not migrated.

These wrappers cover AWG only. Xray has separate [backup/restore commands](xray.md).
For both protocols, restore AWG first, then Xray with `--with-awg`. A's relay
is maintained separately.
