# Russian-address bypass lists

English | [Русский](ru/lists.md)

## Two alternative files

`ru-direct.amnezia.json` sends all RU IPv4 networks from the RIPE snapshot
and local networks directly through the ISP. To reduce the routing table,
it also bypasses some addresses outside that source set. The supplied generic snapshot adds
**111,284,160 addresses**, approximately **2.591% of all IPv4**. Do not use this
policy if every foreign address must go through the VPN.

`ru-services.amnezia.json` selects RU allocations containing addresses of major
Russian services from 86 domain families: Yandex, VK/Mail, public services,
banks, shops, transport, operators, healthcare and education. The complete
selection is in `data/service-roots.txt`. Foreign addresses of those services
are not added. This is not a complete catalog of Russian websites or CDN addresses.

Both include `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `169.254.0.0/16`
and `100.64.0.0/10`. Import one file. Merging them changes which traffic bypasses the VPN and
the number of routes.

| Snapshot | Prefixes | Calculated Android <13 routes | SHA256 |
|---|---:|---:|---|
| `ru-direct` | 1097 | 2004 | `10706c300dbd4122bdaacb166ecb301377bca9734a29aa901923699b29dd4a51` |
| `ru-services` | 77 | 751 | `7ecaa6a95b8e12ffe72b5442723606b7b65cd1f2d6e4638cfc6be3a65e015bb1` |

The generic `ru-direct` was rebuilt without preconfigured VPN-node addresses.
Automated checks reproduce the files offline and verify coverage and route
counts.
A user confirmed that `ru-direct` worked on a phone; the imported file's
SHA256 was not independently verified. Optimized lists also worked on Android
9/10. Other devices and AmneziaVPN versions may handle these routes differently.

## Why the routing table matters

The 8678 collapsed source RU/local prefixes produce 21,751 complement IPv4
prefixes. Including loopback exclusion and IPv6 default, the older Android
calculation gives 21,755 routes. Older Amnezia Android implementations build
a positive VPN-route list and send the large configuration through Binder.
Connection failed with a large list and worked after reduction; a specific
TransactionTooLarge error was not confirmed in the logs.

The `ru-direct` algorithm:

1. Collapse the exact RU/local set and compute its IPv4 complement.
2. Keep VPN prefixes containing DNS 1.1.1.1/1.0.0.1/8.8.8.8 and optional
   `--entry`/`--exit` addresses, plus foreign portions of Google, Cloudflare
   and Telegram ranges.
3. Fill a budget of 2000 VPN prefixes with the largest remaining prefixes.
4. Take the complement: smaller foreign gaps become bypass destinations.

The algorithm preserves source RU coverage by selecting from this CIDR
partition. A global optimum has not been proved. Provider ranges are protected only outside
the RU/local source set. If a **specific** protected IP conflicts with that
set, generation fails without changing existing files. Without `--entry` or
`--exit`, the algorithm contains no deployment-node addresses.

The services variant selects RU allocations containing service addresses,
adds local networks and collapses overlaps. Generation fails above 1000
calculated older-Android routes. The full variant has a 2010-route guard;
the supplied snapshot uses 2004. This models Android <13 configuration behavior,
not a universal OS limit.

## Import format

```json
[
  {
    "hostname": "direct-77-88-0-0-18.invalid",
    "ip": "77.88.0.0/18"
  }
]
```

The routed network is in `ip`. Unique `.invalid` labels work around older
clients losing a mask when a CIDR is put in `hostname`. These labels need no
DNS lookup. Do not replace this schema with arbitrary JSON. Files use UTF-8
without BOM, two-space indentation, LF and a final newline.

Select **addresses from the list must NOT use the VPN** in AmneziaVPN, then
import using **Replace list**. Menu wording varies by client version. On a
separate device, verify that Yandex sees the device's ISP and ipify sees B.
If import prevents a handshake, first disable only the website split list
rather than reinstalling the server.

## Updating

From the repository root, Python 3.10+; no third-party Python packages are needed:

```powershell
python .\update_lists.py --output .\generated\fresh-lists
python .\update_lists.py --entry ENTRY_IPV4 --exit EXIT_IPV4 --output .\generated\protected-lists
python .\update_lists.py --offline --output .\generated\snapshot
```

These commands are separate alternatives. Replace `ENTRY_IPV4`/`EXIT_IPV4`
with your addresses if they need explicit bypass protection. The output
directory must be new. Exactly two importable JSON files are produced;
existing lists are never overwritten on failure. Console output identifies
data provenance, prefixes/routes, additional bypass and SHA256.

Online mode uses RIPEstat, Google/Cloudflare/Telegram, the
`lib4u/amnezia-tunneling-ru` catalog and Google DNS-over-HTTPS for missing
families. `--offline` uses only `data/`; without extra protected IPs it
reproduces the supplied JSON byte for byte. Fresh online output may have
different prefixes and hashes. There is no separate command to save new
source snapshots: online mode writes only JSON. [Data provenance](sources.md).

Deploy copies the repository snapshots without refreshing them or applying
client exclusions. Generate and import a separate result for extra protected
IPs. Check DNS/DoH, IPv6 and foreign CDN behavior on the client separately.
