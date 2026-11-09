# Native VLESS + REALITY + XTLS Vision

English | [Русский](ru/xray.md)

Supported servers run **Debian 12/13 or Ubuntu 22.04/24.04/26.04 LTS amd64**. A forwards
TCP in the kernel; B runs Xray as a separate service. Clients connect to A,
and websites see B's address. No Docker, Go SDK or control
panel is installed on the VPS. REALITY-only mode does not need TUN.

## Installation

Use the [wizard](deploy.md), selecting `reality` or `both`. A clean B can also
be installed manually from a complete repository copy:

```bash
sudo bash servers/install-xray.sh --endpoint EXIT_IPV4 --entry ENTRY_IPV4 --client client1
```

Manual execution needs Python 3, iproute2, OpenSSL and CA certificates; the
wizard installs missing packages. Replace the address placeholders. Installing
B does not configure A. For a manual TCP-only relay on clean A:

```bash
sudo bash servers/install-entry.sh ENTRY_IPV4 EXIT_IPV4 - 32497 443 443
```

`-` disables UDP and the final argument is B's TCP port. Confirm A after
testing as described in the [relay guide](servers.md). For both protocols use
the wizard to coordinate checks and installation order. The `--with-awg`
option accepts only a recognized, healthy native AWG installation of this
toolkit. It refuses other VPNs and firewalls.

## Keys, target and camouflage

Installation generates a server X25519 pair and separate client UUIDs/shortIds.
Target/SNI are selected once or supplied with `--target`. The OpenSSL check
requires TLS1.3/h2/X25519 and a valid certificate for the target hostname.
The client uses REALITY and the Chrome fingerprint, without `allowInsecure`.
Client/server clocks must be correct: the configuration limits tolerated skew.

An ordinary TLS request is handled through the target website; invalid VPN
access must not provide Internet egress. This behavior is tested separately
from authenticated traffic. REALITY does not guarantee invisibility to all DPI.
Checking a target from B does not prove reachability from every client network.
Targets are not automatically changed on failure: arbitrary target/SNI changes
can break camouflage and require coordinated client updates.

Choose a meaningful target; there is no universally ideal site. Official
REALITY materials discuss target selection and public-CDN fallback abuse.
The toolkit adds no public SOCKS/API listeners, Nginx or web panel.
[Official REALITY documentation](https://xtls.github.io/en/config/transports/reality.html).

Client JSON/URI contain UUID, shortId and the REALITY client credential, but
not the private server key. Treat the complete export as secret despite the
historical `publicKey` field name. Adding clients preserves the server key
pair and previously issued identities.

## Service and files

| Path | Purpose |
|---|---|
| `/usr/local/libexec/awg-relay-kit-xray/` | Verified binary, manifest, license and backup bundle |
| `/etc/awg-relay-kit-xray/server.json` | Private state and client registry |
| `/etc/awg-relay-kit-xray/config.json` | Private server configuration |
| `awg-relay-kit-xray.service` | Independent systemd service |
| `/root/awg-relay-kit-xray-clients/NAME/` | Client JSON/URI exports |

The service uses systemd's DynamicUser and LoadCredential to read its
configuration. The original files remain accessible only to root. Xray receives no NET_ADMIN;
NET_BIND_SERVICE permits low TCP ports. New executable directories explicitly
use 0755, private directories 0700 and secret files 0600. Access logging and
verbose debug logging are disabled by default.

The service sets GOMAXPROCS=1 and a soft GC goal of GOMEMLIMIT=96MiB.
The latter is not a hard RSS cap.
No geosite/geoip databases are required. DNS/egress use IPv4; IPv6 destinations
and private service destinations are blocked. RU lists are client routing,
not server GeoIP. Use the same two JSON alternatives for split tunneling.

## Clients and administration

```bash
sudo python3 /opt/awg-relay-kit/install_xray.py add-client --name phone
systemctl status awg-relay-kit-xray.service --no-pager
journalctl -u awg-relay-kit-xray.service -n 30 --no-pager
```

The wizard creates `/opt/awg-relay-kit`; manual deployments use their own
source directory. Adding a client validates the configuration and briefly
restarts Xray, so its sessions reconnect. AWG keeps running. Automated revocation
or target changes are not implemented; manual changes require a private
backup and consistent state/config edits.

Native JSON imports into AmneziaVPN; TXT contains `vless://` for compatible
clients. These are client exports, with server administration through SSH/CLI.
To change an already issued native JSON endpoint:

```powershell
python .\convert_xray.py "C:\secure\client.json" "C:\secure\client-via-entry.json" --entry ENTRY_IPV4 --port 443
```

Only one VLESS REALITY outbound address/port changes. Other fields are preserved,
and existing files are never overwritten. This converter does not handle
`.vpn` or URI; AWG uses `convert_profile.py`.

## Backup and restore

```bash
sudo install -d -m700 /root/private
sudo python3 /opt/awg-relay-kit/install_xray.py backup --output /root/private/xray-backup
# On a different clean B with a source checkout:
sudo python3 install_xray.py restore --backup /root/private/xray-backup --endpoint EXIT_IPV4
```

The output directory must be new. Backup contains private keys and client
exports. For `both`, back up AWG and Xray separately. There is no shared
snapshot, so do not change clients while copying. Restore AWG first,
then Xray with `--with-awg`. Keys/identities survive, but OS SSH accounts and
provider firewall do not transfer. If IP changes, update direct JSON/URI
and the relay destination. Existing via-entry profiles may remain valid
with the same A, keys and SNI. Saved direct exports are not rewritten automatically.

Pinned binary: Xray **26.10.21**. Upstream ZIP SHA256:
`0eec3ed4163c273d8c8bf821f7d219e257921cf584aa3fb970715e458e631978`.
Toolkit bundle SHA256:
`874e6b0a6e2283777083ec49ee98d0c13f39c7e7694e1ebd1fbc4e93ce61bba2`.
The installer checks the code pin, manifest, member allowlist and internal
hashes. Replacing `.sha256` alone does not bypass verification. To reproduce
in a separate checkout without the existing bundle:

```bash
python3 servers/fetch-xray.py
```

The script verifies the official ZIP and retains the executable, license and
provenance. Upgrading requires compatibility checks and explicit pin changes,
not downloading `latest` automatically. [Sources](sources.md).

Ubuntu 24.04/26.04 checks and CPU-image requirements: [LTS report](validation-lts.md).

Debian 12/13 installation, reboot and restore checks: [Debian report](validation-debian.md).
