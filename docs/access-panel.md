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

On Windows, double-click `COLDWIRE-Admin.cmd` in the extracted folder. The launcher opens the installation saved in that folder first. If the folder is new, it checks for an existing installation in `%LOCALAPPDATA%\COLDWIRE\access-panel`. When it finds neither, it starts setup.

To open a specific installation, run this from the extracted folder in PowerShell.

```powershell
.\COLDWIRE-Admin.cmd --folder "C:\path to\operator files"
```

On Linux, open a terminal in the extracted folder and run

```bash
bash COLDWIRE-Admin.sh
```

The Linux launcher checks the extracted folder first, then `${XDG_DATA_HOME:-$HOME/.local/share}/coldwire/access-panel`. It starts setup if neither location has an installation. To open a different one, pass `--folder "/path to/operator files"`.

Enter A’s IPv4, SSH username and password, then do the same for B. Append `:port` when a server’s SSH service uses a port other than 22. The launchers install their Python dependencies into `.venv`. The installer saves the SSH host keys on first contact and rejects later changes. If you run from a source checkout, install Go on your administration computer to build the SPA binary.

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

To rotate a device key, issue a replacement under the same user, test the new profile and revoke the old device. Back up `private/coldwire-installation/`. It holds the operator’s SSH and SPA keys, server fingerprints and the exported profiles. Give each user only their device’s profile.

### Import an AmneziaVPN export

Choose **8** and select the `.vpn` file. Its AmneziaWG peer must already be registered on B. Use the same device name to export another copy for a peer already managed by the panel. If an administrator export lacks client data, provide a matching direct client `.vpn` from B when prompted.

The panel writes `<device>-coldwire.vpn` and preserves the source file and the peer’s AmneziaWG keys. Administrator exports keep their server management fields. Use the panel to reach the locked-down SSH endpoints.

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
