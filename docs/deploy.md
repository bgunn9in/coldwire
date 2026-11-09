# Automated AWG, REALITY or dual-protocol deployment

English | [Русский](ru/deploy.md)

`deploy.py` runs on your computer and configures two separate clean servers
running **Debian 12/13 or Ubuntu 22.04/24.04/26.04 LTS amd64**. Other OS
releases are rejected.
Servers need password-based SSH, root or sudo, assigned public IPv4 addresses
and APT access. TUN is required on B only for AWG. Additional provider-side NAT
is unsupported in normal mode; the private-address flag is for the lab.

Use clean servers: the installer refuses an existing toolkit installation,
Docker, enabled forwarding, active UFW or nftables tables from other software.
It does not migrate existing VPNs or firewall rules, enable a VPN on your
computer or change your computer's routes.

## Start the wizard

Install standard CPython **3.10+** with venv/pip on your computer first. The launcher
creates `.venv` and installs the pinned dependency. On the servers, the wizard
installs missing Python, iproute2, OpenSSL and CA-certificate packages after
checking the OS and existing state of both machines.

On Windows, the launcher selects an installed standard CPython version.
An existing venv built with free-threaded Python is rejected before pip runs.
Rename that folder to keep a backup, then rerun the launcher.

Windows PowerShell, from the repository root:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

This ExecutionPolicy setting applies only to the launched process. macOS/Linux:

```bash
bash setup.sh
```

The wizard asks for:

1. Protocol: AWG 3.1, REALITY or both.
2. A's IPv4, SSH port (Enter = 22), login (Enter = root) and hidden password.
3. The same SSH details for B.

The installer generates keys, UUIDs and shortIds, detects interfaces and
selects a REALITY target/SNI. You can set the ports and target yourself.
It saves the results in a new private directory,
`private/deployment-<UTC-time>-<suffix>/`, without SSH passwords in the report
or VPN profiles.

## SSH identity and initial trust

The interactive wizard uses TOFU: the first SSH key is saved in
`private/known_hosts`. It rejects a changed key before sending a password.
To verify the first key independently, supply known fingerprints through
`--entry-fingerprint` and `--exit-fingerprint`.
`--strict-host-keys` disables automatic first-contact trust in the wizard.
After reinstalling a VPS, verify its new key through the provider console
rather than disabling identity checking.

Non-interactive first contact requires explicit `--accept-new-host-keys` or
known fingerprints. Existing server SSH keys and settings are not changed.

## Modes and ports

| Selection | A | B |
|---|---|---|
| `awg` | UDP relay, default 32497 | AWG 3.1 / systemd |
| `reality` | TCP relay, default 443 | VLESS + REALITY + XTLS Vision |
| `both` | Both protocols in one relay table | Two independent services |

Supply options in advance; the wizard asks for missing inputs:

```powershell
.\.venv\Scripts\python.exe deploy.py --protocol both --entry ENTRY_IPV4 --exit EXIT_IPV4 --entry-user root --exit-user ubuntu --entry-ssh-port 22 --exit-ssh-port 2222
```

Replace `ENTRY_IPV4`/`EXIT_IPV4` with your public addresses.
`--entry-port`/`--exit-port` select **AWG UDP** ports, default 32497.
`--reality-entry-port`/`--reality-exit-port` select **REALITY TCP** ports, default
443 when not explicitly supplied. If SSH occupies that port on the same
address, the wizard may select free 8443; SSH is never reconfigured. Other
occupied ports, or conflicts with an explicitly requested port, cause failure.
TCP and UDP are checked separately; Xray does not reserve UDP443.

`--entry-ssh-host`/`--exit-ssh-host` override the SSH transport address, for
example localhost for VM port forwarding. The VPN IPv4 must still be assigned
to the server. SSH ports and VPN ports are independent options.

Optional `--reality-target HOST[:PORT]` selects a REALITY target website.
Otherwise a candidate is selected after checking TLS1.3, h2, X25519 and the
certificate. Its SNI is saved in profiles and the report. Reboot and restore
do not change it. [REALITY configuration and limits](xray.md).

Allow the selected VPN ports in your provider firewall while preserving SSH.
SSH alone cannot manage that external firewall without a provider API. The
automatic probe checks the server path, not every possible client network.

## Non-interactive execution

Supply passwords through environment variables from a secret manager:

| Variable | Purpose |
|---|---|
| `AWG_ENTRY_PASSWORD` | A's SSH password, all three modes |
| `AWG_EXIT_PASSWORD` | B's SSH password, all three modes |
| `AWG_ENTRY_SUDO_PASSWORD` | Optional separate sudo password on A |
| `AWG_EXIT_SUDO_PASSWORD` | Optional separate sudo password on B |

The AWG prefix is retained for compatibility. Choose other password variable
names with `--entry-password-env`/`--exit-password-env`. Do not place password
values in command-line arguments or shell history.

```powershell
.\.venv\Scripts\python.exe deploy.py --protocol both --entry ENTRY_IPV4 --exit EXIT_IPV4 --entry-user root --exit-user root --non-interactive --accept-new-host-keys
```

Without `--protocol`, non-interactive mode defaults to AWG for compatibility.
Root does not need sudo; NOPASSWD is detected. A sudo password is sent only to
sudo's stdin, not inherited as input by the installer. MFA, `requiretty` and
mandatory password-change flows are unsupported.

## Sequence and failure handling

1. Validate arguments, SSH identity, root/sudo and different machine IDs.
2. Upload an explicit allowlist of public toolkit files to private staging directories.
3. Check both servers, then install missing dependencies.
4. Check ports, binary bundles and the requirements of the selected protocols.
5. Install B. In `both`, install AWG and download its profiles immediately,
   then install Xray and download its profiles. Xray failure retains downloaded AWG access.
6. Install A and arm an independent five-minute rollback timer.
7. Run authenticated probes of every selected protocol through A. Xray also
   checks an HTTPS response and A's address as seen by B.
8. Cancel the timer only after all probes pass, write the report, remove
   temporary staging files and close SSH connections.

The AWG probe creates a temporary peer; the Xray probe starts a temporary
local client. Neither changes the operator's routes or server default routes.
Temporary processes and the probe peer are removed on completion.

If setup is not confirmed, A rolls back even if SSH disconnects. B and
downloaded profiles remain available. Running the installer again does not
resume setup: it refuses to overwrite existing directories and keys. Inspect
the retained files to diagnose a partial installation. The transient timer
does not survive reboot, so do not reboot A before confirmation.

Error messages omit private configuration. Xray identifies the failed step
with a code such as `XRAY_TLS_TARGET` or `XRAY_ACTIVATION`; see
[troubleshooting](troubleshooting.md).

## Results

| Files | Purpose |
|---|---|
| `client.vpn` / `client.conf` | Direct AWG to B |
| `client-via-entry.vpn` / `.conf` | AWG through A |
| `xray-client.json` / `.txt` | Direct REALITY; TXT contains a VLESS URI |
| `xray-client-via-entry.json` / `.txt` | REALITY through A |
| Two `ru-*.amnezia.json` files | Alternative client bypass lists |
| `deployment.md` | Mode, addresses, ports, SNI, SSH fingerprints and result, without passwords |

Only selected protocols are exported. Direct and via-entry files for one
protocol represent one client, not separate access for different devices.
In `both`, users choose between two independent client connections. Native
servers are administered through CLI/SSH; no Amnezia administrator role is created.

The RU files are generic snapshots: deployment neither refreshes them online
nor imports them into the application. Select one and use Replace list in
the bypass-VPN mode. [Updating lists](lists.md). Profiles contain secrets;
restrict the output folder with NTFS ACLs on Windows. Unix chmod is not a
substitute for Windows ACLs. Keep exports out of the public source tree.

## Lab verification

The [Ubuntu 22.04 report](validation-protocols.md) covers all three modes,
reboots, restore, service independence, authorization and resource use.
AWG also passed an [earlier full cycle](validation-native.md). The lab requires
explicit `--allow-private-endpoint`; it does not bypass foreign firewalls or
permit installing over an existing VPN.

Ubuntu 24.04/26.04 checks and CPU-image requirements: [LTS report](validation-lts.md).

Debian 12/13 installation, reboot and restore checks: [Debian report](validation-debian.md).
