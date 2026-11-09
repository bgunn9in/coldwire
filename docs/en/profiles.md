# Client and administrator profiles

[Русский](../profiles.md) · **English**

## What the converter changes

This section covers AWG and `convert_profile.py`. REALITY uses a separate
native JSON converter, `convert_xray.py`, described below.

Export encoding is `vpn://` → Base64URL → Qt `qCompress` (four-byte big-endian
original length plus zlib) → UTF-8 JSON. The script limits size, checks the
header and stream ending, and decodes its result again. Decoded JSON is not
printed or written to disk.

It supports `.vpn` with one **amnezia-awg2** container. Full application
backups, QR images, native `.conf`, other protocols and multiple-container
profiles are unsupported. First export a separate AmneziaWG access profile
for those cases. The converter needs Python 3.10+ on Windows/macOS/Linux.

| Field | Client export | Administrator export |
|---|---|---|
| Top-level `hostName` | A | **B**, SSH/management address |
| Top-level SSH `port` and credentials | Preserved | **Preserved** |
| `containers[0].awg.port` | A's entry port | **Real AWG port on B**, preserved |
| `last_config.hostName` / `port` | A / entry port | A / entry port |
| `last_config.config` → `Endpoint` | A:entry-port | A:entry-port |
| `description` | Label with new entry address | Label with new entry address |
| Keys, peer IP, PSK, H/S/J and other parameters | Preserved | Preserved |

The relay is transparent to AWG: the existing client key remains registered
on B. Conversion does not create users or connect to servers. `--entry` is
required; replace `ENTRY_IPV4` with your entry address. `--port` defaults to
32497. No server addresses are preconfigured.

## A normal new client

1. In the application's administrator connection to B, create a **separate
   client for the new device**.
2. Save the original export in a private directory outside the repository.
3. Test original direct access to B on a spare device.
4. Create a new copy:

```powershell
python .\convert_profile.py "C:\secure\phone.vpn" "C:\secure\phone-via-entry.vpn" --entry ENTRY_IPV4 --port 32497
```

5. Import as a separate connection without deleting the old one. Test websites
   and external IP.
6. Save/export the previous bypass list, then import one selected new JSON.

The output parent directory must exist; the output file must not. Existing
files, including the input file, are never overwritten. Unix output mode is
0600. On Windows use a directory restricted to the intended user: chmod 0600
does not replace NTFS ACLs. Never upload profiles to GitHub, even a private repo.

For a native exit installed with `servers/install-exit.sh`, no application is
needed for export: `python3 install_exit.py add-client --name phone` generates
registered `.vpn`/`.conf` access, including a via-entry variant if `--entry`
was configured. These are client profiles without an Amnezia administrator
role. The native CLI does not import administrator access for another exit.

Do not run one AWG peer concurrently on two devices: its Endpoint may move
between them. Issue separate access instead.

## Administrator export

Administrator exports often contain SSH credentials and server parameters
but **no client `last_config`**. Such a file cannot recover a private client
key. The converter then stops without creating an output.

Two supported cases:

- If a complete working `last_config` is present, the normal command suffices.
- Otherwise supply a separate **fresh direct client export for the same B**:

```powershell
python .\convert_profile.py "C:\secure\admin.vpn" "C:\secure\admin-via-entry.vpn" --entry ENTRY_IPV4 --client-profile "C:\secure\this-device-direct.vpn" --port 32497
```

The converter checks the B address and server container/protocol parameters,
then takes client keys from the second file. Use access assigned to this
device, not an active phone. Files alone cannot prove the peer remains
registered; the original client must work directly.

The administrator's top-level address remains **your B** and its original
SSH port. SSH on A reaches the relay, not the AWG server. Only the nested
client Endpoint points to **your A and entry port**. Consequently, the
administrator connection's UI may still display B's address.

The checked AmneziaVPN 5.1.0.6 uses an existing client cache. Clearing or
regenerating configuration, reinstalling the protocol, changing protocol
settings or using a different application version may recreate Endpoint B.
After such changes, export the current profile, reconvert and verify the
entry. New access issued by the application for B also needs conversion.

Replacing top-level B with A sends administration to the relay, where AWG is
not installed. Administrator status does not fix UDP reachability. Port 32497
is the common default for all OS clients; there is no Windows-specific mode.
[AdGuard compatibility observation](windows-admin-port-diagnosis.md).

## Import on devices

In AmneziaVPN, add a connection from a file/key and select the new `.vpn`.
Exact menu names vary; importing one connection is different from restoring
the complete settings backup. Keep the old connection as a separate fallback.

For bypass: Settings → Split tunneling → websites/IPs → **addresses in the
list must NOT use the VPN** → import JSON → **Replace list**. Select one
variant. If necessary, disconnect only the test VPN while changing its list.
macOS/iOS work with IPs/subnets, already present in these files. On
Windows/Android an IP exclusion also affects applications accessing that IP.

After connecting, Yandex Internetometer should see the ISP address and
`https://api.ipify.org` should see **your B's IPv4**. Disable other browser
proxies, Private Relay or browser VPNs for the check so they do not add a
different path. [Troubleshooting](troubleshooting.md).

## REALITY profiles

The wizard and `install_xray.py add-client` export direct and via-entry native
JSON plus TXT files containing `vless://`. Import native JSON as a third-party
Xray configuration in AmneziaVPN. URI use requires a client supporting VLESS
REALITY / XTLS Vision. The private server key is never exported.

```powershell
python .\convert_xray.py "C:\secure\xray-client.json" "C:\secure\xray-via-entry.json" --entry ENTRY_IPV4 --port 443
```

Only the address/port of one VLESS REALITY outbound changes. UUID, shortId,
SNI, REALITY client credential and remaining fields are preserved. The
converter does not handle URI or `.vpn` and never overwrites files. A's TCP
relay must match the endpoint. Direct and via-entry copies are alternatives
for one access; they do not replace separate access for different devices.

In `both`, import AWG and REALITY as different connections. RU lists remain
client routing settings, not server Xray routing rules. [Xray maintenance](xray.md).
