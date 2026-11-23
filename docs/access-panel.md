# Install and manage a COLDWIRE relay

[Русский](ru/access-panel.md) · [Project home](../README.md)

## 1. Prepare both servers

Use two clean amd64 servers with systemd. The supported releases are Ubuntu 22.04, 24.04 and 26.04 LTS and Debian 12 and 13. Each server needs its own public IPv4 and a working SSH login with root or sudo access. The relay uses IPv4 for administration and VPN egress. Check that you can reach both rescue consoles from the provider’s dashboard.

The installer deploys COLDWIRE directly to both hosts without Docker. On B, AmneziaWG 3.1 runs as a systemd service.

If your provider has a separate cloud firewall, allow these connections before you start. The installer manages the firewall inside each VPS.

| Destination | Allow at the provider |
| --- | --- |
| A, entry | Current SSH from your computer for setup. TCP 22222–22253 for management. UDP 62201 for SPA and UDP 32497 for AmneziaWG. |
| B, exit | Current SSH from your computer for setup. TCP 22222–22253 and UDP 32497 from A’s IPv4. |

The installer picks an available SSH port in that TCP range on each node. It closes the original SSH path on the WAN after testing the replacement. Once the new path works, you can remove your provider’s bootstrap SSH rules. Keep a working rescue console for recovery.

## 2. Run the installer

On the computer you use for administration, install standard CPython 3.10 or newer and the OpenSSH client. On Ubuntu and Debian the packages are `python3`, `python3-venv` and `openssh-client`.

Download and extract `COLDWIRE-Access-Panel.zip`. It includes the launchers and the Linux SPA server binary. [Latest panel release](https://github.com/bgunn9in/coldwire/releases/latest)

On Windows, double-click `COLDWIRE-Admin.cmd` in the extracted folder. The launcher looks for an installation in that folder first, then in `%LOCALAPPDATA%\COLDWIRE\access-panel`. If both locations are empty, the panel offers **Install COLDWIRE**.

To open a specific installation, run this from the extracted folder in PowerShell.

```powershell
.\COLDWIRE-Admin.cmd --folder "C:\path to\operator files"
```

On Linux, open a terminal in the extracted folder and run

```bash
bash COLDWIRE-Admin.sh
```

The Linux launcher checks the extracted folder first, then `${XDG_DATA_HOME:-$HOME/.local/share}/coldwire/access-panel`. To open a different installation, pass `--folder "/path to/operator files"`.

Choose **Install COLDWIRE** and enter A’s IPv4, SSH username and password, then do the same for B. Append `:port` when the server uses a different SSH port. The panel opens the management menu when setup is complete. The launchers install Python dependencies into `.venv`. The installer saves the SSH host keys on first contact and rejects later changes. If you run from a source checkout, install Go on your administration computer to build the SPA binary.

The installer checks both nodes, starts AmneziaWG on B and verifies the relay through A. It then stages the firewall rules and checks a fresh SSH connection through SPA plus an AmneziaWG handshake before confirming the final rules. Each lockdown stage has a three-minute rollback timer. A reboot also discards an unconfirmed stage.

After the installer confirms the rules, systemd loads the saved WAN policy before starting SSH or the VPN. On A, management SSH, the SPA service and the relay also wait for the SPA admission policy.

## 3. Connect your first device

1. Install COLDWIRE Amnezia VPN on the device. [VPN client guide](https://github.com/bgunn9in/COLDWIRE-amnezia-client/blob/feature/spa-admission/docs/spa.md)
2. Copy `private/coldwire-installation/client1.vpn` to the device over a private channel. Import it through **+** and **File with connection settings**.
3. Connect and check the public IPv4 from a site routed through the VPN. It should be B’s IPv4. If you enable split tunneling, a site routed directly should see your ISP’s IP. [Split-tunneling lists](lists.md)

## 4. Add, revoke or import profiles

Run the same launcher again to open the panel.

| Menu item | What it does |
| --- | --- |
| `1 Status` | Checks both nodes and shows their SSH endpoints and firewall status. |
| `2 List users and devices` | Lists profiles and their assigned users. |
| `3 Add device and export profile` | Issues an AmneziaWG peer and SPA key. Reuse the user name to group several devices. |
| `4 Revoke device` | Removes that device’s VPN peer and SPA key. |
| `5 SSH to entry` / `6 SSH to exit` | Opens a shell through the administrative SPA path. The connection to B goes through A. |
| `7 Revoke user and all their devices` | Revokes every device assigned to that user. |
| `8 Import an AmneziaVPN profile` | Converts an existing AmneziaWG 3.1 export and adds a device SPA key if needed. |
| `9 Exit migration` | Starts, checks, confirms or rolls back a move from Docker to systemd. Shown for installations with pilot SPA and a Docker or migrated exit. |
| `10 Restore from backup` | Checks a `.cwbackup`, restores an operator folder or exports the files needed to recover A and B. Available before installation too. |
| `11 Create backup` | Reads both nodes over administrative SSH and saves an encrypted copy with the operator folder. |

To rotate a device key, issue a replacement under the same user, test the new profile and revoke the old device. Back up `private/coldwire-installation/`. It holds the operator’s SSH and SPA keys, server fingerprints and the exported profiles. Give each user only their device’s profile.

### Import an AmneziaVPN export

Choose **8** and select the `.vpn` file. Its AmneziaWG peer must already be registered on B. Use the same device name to export another copy for a peer already managed by the panel. If an administrator export lacks client data, provide a matching direct client `.vpn` from B when prompted.

The panel writes `<device>-coldwire.vpn` and preserves the source file and the peer’s AmneziaWG keys. Administrator exports keep their server management fields. Use the panel to reach the locked-down SSH endpoints.

### Keep pilot SPA on A after migrating B

Open the existing installation in the panel and choose **9 Exit migration**. The tested setup is Ubuntu 22.04 amd64 with one WAN interface on B, an IPv4 tunnel subnet and a `/32` route for each peer address. The operator folder needs the matching guest export in `legacy-template.vpn`.

1. In the maintenance window, choose **2 Start migration**. The panel backs up the container configuration on B and arms a ten-minute rollback before switching the UDP port to the native service.
2. Test SSH through A and send traffic using an existing VPN profile. Choose **3 Confirm migration**. The panel checks for a fresh peer handshake and traffic on B before it updates `operator.json`.
3. If a check fails, choose **4 Roll back** to restore the container. The timer also restores it if the trial expires, including if SSH becomes unavailable. Use **1 Migration status** to check the result. Add or revoke devices after confirmation or rollback.

Docker stays available for recovery. Native boot and shutting down Docker can be checked in a separate window.

For a manual migration, configure the panel as follows.

After B has moved from Docker to systemd, set `pilot_spa` to `true` in the operator folder’s `operator.json`. Set `native_exit` to an object with the absolute Linux paths `awg` and `config`. Use the native `awg` executable on B and the same configuration file its service reads at startup. Keep the working guest export in `legacy-template.vpn` so new profiles use the existing connection parameters.

The add and revoke commands update B’s saved configuration and running interface by peer public key. The panel still registers and revokes SPA keys on A through `coldwire-spa-pilot.service`.

## Create an encrypted backup

Start the panel with the operator folder for this installation and choose **11 Create backup**. Press Enter for the default backup folder, or enter a different path on the operator computer. The panel uses your existing SPA and SSH keys to collect both nodes. Wait for pending firewall changes or migrations to finish before taking a backup.

The panel prints the paths to the encrypted `.cwbackup` and its recovery key. On Windows, the default key uses DPAPI and opens in the Windows profile that created it. Choose a portable key if you need to recover on another computer. Linux always uses a portable key and asks for a passphrase. Save the key separately from the archive and keep the passphrase separately from both files.

You can also run the backup from the command line.

```powershell
.\COLDWIRE-Admin.cmd backup
```

```sh
bash COLDWIRE-Admin.sh backup
```

Use `--folder "PATH"` before `backup` for a nonstandard operator folder. Use `--to "PATH"` after `backup` to choose a destination. On Windows, add `--portable-key` to protect the key with a passphrase.

## Restore from an encrypted backup

Open **10 Restore from backup**, then choose **1 Check backup**. Enter the path to the `.cwbackup` file, or press Enter to use the latest backup in the local data folder. At the key prompt, press Enter to use the matching key in the local `backup-keys` folder. If you moved or renamed either file, enter the key path explicitly.

- **2 Restore operator folder** writes the operator files into a new folder. Open it with `COLDWIRE-Admin.cmd --folder "PATH"` on Windows or `bash COLDWIRE-Admin.sh --folder "PATH"` on Linux. Keep the existing folder until you verify access from the restored one.
- **3 Export A and B for recovery** saves the two server archives, their checksums, the original addresses and WAN interfaces in `network.json`, a Linux recovery script and the panel package from the backup. Keep the export on a private local disk. It contains unencrypted keys.
- **4 Save a portable recovery key** creates a separate key file protected by a passphrase. Create it while the original Windows profile can still unlock the backup. Enter that file at the key prompt on the recovery computer. Keep the passphrase separately.

To recover a server, mount a prepared Linux system disk from the provider’s rescue console. Use the same OS release and architecture, WAN interface name and addresses recorded at capture time. Install the original system dependencies on the target disk, including OpenSSH, nftables and conntrack, and make sure the account used for COLDWIRE SSH exists there. If the VPS addresses or WAN interface changed, update the restored firewall, relay, SSH bind settings, panel endpoints and client profiles before exposing the new nodes.

Copy the recovery script, the matching node archive and `SHA256SUMS` to the same directory on the rescue system. Run the appropriate command, with `/mnt/server` set to that node’s mounted root.

```sh
sudo python3 restore_backup.py exit --root /mnt/server
sudo python3 restore_backup.py entry --root /mnt/server
```

Recover and boot B first, then A. Check SSH through SPA and connect with an existing VPN profile. The backup contains COLDWIRE data and service files. The replacement disk supplies the OS, accounts and provider network settings.

## Troubleshooting

- If setup stops during a firewall change, give the pending stage up to three minutes to roll back. Check the messages and the provider’s console before retrying. The installer tests the new route before closing the old one. A confirmed stage stays in effect, so use the console if you lose the keys.
- If the WAN firewall fails to load on reboot, use the provider’s console to restore a working copy of `/etc/coldwire-lockdown/active.nft`. Reboot and check access through the panel.
- If A fails to load its SPA admission policy, restore `/etc/coldwire-access/active.nft` for a new installation or `/var/lib/coldwire-spa-pilot/pilot.nft` for a pilot installation. Reboot and check access.
- If SSH through the panel fails, check that the provider allows A’s SPA UDP port and the chosen SSH port. Check B’s rule from A’s IPv4. A reported SSH host key change should be checked against the provider console.
- If VPN access fails, confirm that the app and imported profile are from COLDWIRE. In the panel, check the two nodes and the device’s registration. The client guide explains how to export a log.
- To move the panel, copy the private folder and pass its path with `--folder PATH`. On Linux, give the directory mode `700` and the SSH private key `ssh` mode `600`.

## Tested configurations

Clean amd64 tests ran on all five supported server releases with one vCPU and 1 GiB of RAM per guest. They covered the installer, blocked bootstrap SSH, device issue and revocation, timer and reboot rollback, and a normal restart of A. The launcher also ran on Windows 11 and all five Linux releases. On a Debian 13 relay, converted client and administrator exports passed tunnel traffic and the original files kept their checksums.

On a Debian 13 node running the SPA pilot, losing the WAN policy left the administrative SPA override and key file intact, even with an old `pilot-upgrade` marker present. Restoring the policy through the console was enough to reopen access after reboot. A confirmed firewall stage clears the marker. [Pilot recovery test](pilot-upgrade-recovery.md)
