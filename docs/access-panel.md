# Install and manage a COLDWIRE relay

[Русский](ru/access-panel.md) · [Project home](../README.md)

This guide follows the panel in `main`. If a menu item is missing, download the latest release or use the current source.

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

Download and extract `COLDWIRE-Access-Panel.zip`, or clone the repository to use `main`. The release ZIP bundles the Linux SPA server binary. For a new installation from source, install Go on the operator computer so the panel can build that binary. [Panel releases](https://github.com/bgunn9in/coldwire/releases/latest)

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

Choose **Install COLDWIRE**. Enter A’s IPv4, SSH username and password, then repeat for B. Append `:port` if SSH uses a port other than 22. The launchers install their Python dependencies into `.venv`. The installer records each SSH host key and checks it on later connections. When setup completes, the management menu opens.

The installer checks both nodes, starts AmneziaWG on B and verifies the relay through A. It then stages the firewall rules and checks a fresh SSH connection through SPA plus an AmneziaWG handshake before confirming the final rules. Each lockdown stage has a three-minute rollback timer. A reboot also discards an unconfirmed stage.

After the installer confirms the rules, systemd loads the saved WAN policy before starting SSH or the VPN. On A, management SSH, the SPA service and the relay also wait for the SPA admission policy.

## 3. Connect your first device

1. Install COLDWIRE Amnezia VPN on the device. [VPN client guide](https://github.com/bgunn9in/COLDWIRE-amnezia-client/blob/feature/spa-admission/docs/spa.md)
2. Find `client1.vpn` in the operator folder, which defaults to `private/coldwire-installation/` for a new setup. Send the file privately and import it through **+** and **File with connection settings**.
3. Connect and check the public IPv4 from a site routed through the VPN. It should be B’s IPv4. If you enable split tunneling, a site routed directly should see your ISP’s IP. [Split-tunneling lists](lists.md)

## 4. Manage the relay

Run the same launcher again to open the panel.

| Menu item | What it does |
| --- | --- |
| `1 Status` | Checks both nodes and shows their SSH endpoints and firewall status. |
| `2 List users and devices` | Lists profiles and their assigned users. |
| `3 Add device and export profile` | Registers the AmneziaWG peer on B and its SPA key on A, then writes `<device>.vpn` into the operator folder. |
| `4 Revoke device` | Removes that device’s VPN peer and SPA key. |
| `5 SSH to entry` / `6 SSH to exit` | Opens a shell through the administrative SPA path. The connection to B goes through A. |
| `7 Revoke user and all their devices` | Revokes every device assigned to that user. |
| `8 Import an AmneziaVPN profile` | Converts an existing AmneziaWG 3.1 export and adds a device SPA key if needed. |
| `9 Exit migration` | Starts, checks, confirms or rolls back a move from Docker to systemd. Shown for installations with pilot SPA and a Docker or migrated exit. |
| `10 Restore from backup` | Checks a `.cwbackup`, restores an operator folder or exports the files needed to recover A and B. Available before installation too. |
| `11 Create backup` | Reads both nodes over administrative SSH and saves an encrypted copy with the operator folder. |
| `12 Update split-tunneling lists` | Writes two AmneziaVPN exclusion lists locally. Available before installation, with no SSH credentials required. |

After running **12**, use the path printed by the panel to find the JSON files. Import the one you want in AmneziaVPN. [Split-tunneling guide](lists.md)

Give each device a unique name. Use the same user name for several devices when you want to manage them together. To rotate a device key, add a replacement, test its profile, then revoke the old device. Send users only their own device profiles. The operator folder also holds administrative keys and pinned SSH host keys.

### Import an AmneziaVPN export

Choose **8** and select the `.vpn` file. Its AmneziaWG peer must already be registered on B. Use the same device name to export another copy for a peer already managed by the panel. If an administrator export lacks client data, provide a matching direct client `.vpn` from B when prompted.

The panel writes `<device>-coldwire.vpn` and preserves the source file and the peer’s AmneziaWG keys. Administrator exports keep their server management fields. Use the panel to reach the locked-down SSH endpoints.

### Move a Docker-based exit to systemd

Open the existing installation in the panel and choose **9 Exit migration**. The tested setup is Ubuntu 22.04 amd64 with one WAN interface on B, an IPv4 tunnel subnet and a `/32` route for each peer address. The operator folder needs the matching guest export in `legacy-template.vpn`.

1. In the maintenance window, choose **2 Start migration**. The panel backs up the container configuration on B and arms a ten-minute rollback before switching the UDP port to the native service.
2. Test SSH through A and send traffic using an existing VPN profile. Choose **3 Confirm migration**. The panel checks for a fresh peer handshake and traffic on B before it updates `operator.json`.
3. If a check fails, choose **4 Roll back** to restore the container. The timer also restores it if the trial expires, including if SSH becomes unavailable. Use **1 Migration status** to check the result. Add or revoke devices after confirmation or rollback.

Schedule a separate maintenance window to test a native boot and disable Docker if needed.

If B was migrated outside the panel, open the operator folder’s `operator.json`. Set `pilot_spa` to `true` and add `native_exit` with the absolute paths `awg` and `config` on B. Use the executable and configuration file that the running native service uses. Keep its guest profile as `legacy-template.vpn`.

The add and revoke commands update B’s saved configuration and running interface by peer public key. The panel still registers and revokes SPA keys on A through `coldwire-spa-pilot.service`.

## Create an encrypted backup

Choose **11 Create backup** from the installation’s management menu. B must already run native AmneziaWG, either from the installer or after the panel’s exit migration. Pilot SPA on A is supported. Finish any pending firewall change or migration before backing up.

Accept the default destination or choose another directory on the operator computer. The panel reads both nodes over the existing administrative SSH path, encrypts the server files and operator folder, then prints the paths to the archive and key.

| Operator OS | Default archive folder | Recovery key folder |
| --- | --- | --- |
| Windows | `%LOCALAPPDATA%\COLDWIRE\backups` | `%LOCALAPPDATA%\COLDWIRE\backup-keys` |
| Linux | `${XDG_DATA_HOME:-$HOME/.local/share}/coldwire/backups` | `${XDG_DATA_HOME:-$HOME/.local/share}/coldwire/backup-keys` |

Windows protects the default `.key.dpapi` file with the profile that created it. Choose a portable `.key.cwkey` if you need to recover on a different computer. Linux always uses a portable key and asks for a passphrase. Keep the recovery key separately from the archive and the passphrase separately from both.

To run the backup from a terminal, use the launcher for your OS.

```powershell
.\COLDWIRE-Admin.cmd backup
```

```sh
bash COLDWIRE-Admin.sh backup
```

Pass `--folder "PATH"` before `backup` for a nonstandard operator folder. After `backup`, use `--to "PATH"` to move the archive destination or `--portable-key` on Windows to choose passphrase protection.

## Restore from an encrypted backup

Open **10 Restore from backup**, available before installation too. Choose **1 Check backup** and enter the archive path, or press Enter for the most recent local copy. Press Enter at the key prompt if the key is in the default folder and its name matches the archive. Otherwise, enter the key path.

- **2 Restore operator folder** writes to a new folder. Launch the panel with `--folder "PATH"` and use **1 Status** to verify access.
- **3 Export A and B for recovery** writes the node archives, checksums, `network.json`, the Linux recovery script and a copy of the panel. The export contains unencrypted keys and the original network settings. Save it on a private local disk.
- **4 Save a portable recovery key** protects an existing backup’s key with a passphrase. Create it while you can still unlock the backup. On the recovery computer, enter its path at the key prompt.

### Restore a server disk

From the provider’s rescue console, mount a clean Linux system disk with the same OS release and architecture. Prepare the COLDWIRE SSH account and install the packages from the original setup. These include OpenSSH and nftables, plus conntrack on a pilot entry and iptables on a migrated exit. Check the WAN interface and addresses against `network.json`. If either changed, update the restored firewall, relay, SSH binding and panel endpoints before bringing the node online. Update client profiles if A’s endpoint changed.

Copy the recovery script, the matching node archive and `SHA256SUMS` to the same directory in rescue mode. Run the command for that node, using its mounted root as `--root`.

```sh
sudo python3 restore_backup.py exit --root /mnt/exit
sudo python3 restore_backup.py entry --root /mnt/entry
```

Restore and boot B first, then A. Check SSH through SPA and test an existing profile. The archive saves COLDWIRE configuration and services. The system disk supplies the OS, accounts and provider network settings.

## Troubleshooting

- If setup stops during a firewall change, give the pending stage up to three minutes to roll back. Check the messages and the provider’s console before retrying. The installer tests the new route before closing the old one. A confirmed stage stays in effect, so use the console if you lose the keys.
- If the WAN firewall fails to load on reboot, use the provider’s console to restore a working copy of `/etc/coldwire-lockdown/active.nft`. Reboot and check access through the panel.
- If A fails to load its SPA admission policy, restore `/etc/coldwire-access/active.nft` for a new installation or `/var/lib/coldwire-spa-pilot/pilot.nft` for a pilot installation. Reboot and check access.
- If SSH through the panel fails, check that the provider allows A’s SPA UDP port and the chosen SSH port. Check B’s rule from A’s IPv4. A reported SSH host key change should be checked against the provider console.
- If VPN access fails, confirm that the app and imported profile are from COLDWIRE. In the panel, check the two nodes and the device’s registration. The client guide explains how to export a log.
- To move the panel, copy the private folder and pass its path with `--folder PATH`. On Linux, give the directory mode `700` and the SSH private key `ssh` mode `600`.

## Tested configurations

Clean amd64 tests ran on all five supported server releases with one vCPU and 1 GiB of RAM per guest. They covered the installer, blocked bootstrap SSH, device issue and revocation, timer and reboot rollback, and a normal restart of A. The launcher also ran on Windows 11 and all five Linux releases. On a Debian 13 relay, converted client and administrator exports passed tunnel traffic and the original files kept their checksums.

Both exclusion lists were generated from menu 12 and the standalone launcher on Ubuntu 22.04, 24.04 and 26.04 and on Debian 12 and 13. [Linux test results](lists.md#linux-test-results)

On a Debian 13 node running the SPA pilot, losing the WAN policy left the administrative SPA override and key file intact, even with an old `pilot-upgrade` marker present. Restoring the policy through the console was enough to reopen access after reboot. A confirmed firewall stage clears the marker. [Pilot recovery test](pilot-upgrade-recovery.md)

Backup tests used an isolated Ubuntu 22.04 lab with one vCPU and 1 GiB of RAM per server. The panel created copies from Windows and Linux, opened a portable Linux backup on Windows, and restored the operator folder and both server file sets to offline roots. The lab covered fresh native installations and pilot SPA with a migrated native exit.
