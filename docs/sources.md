# Sources and verification boundaries

English | [Русский](ru/sources.md)

Documentation was checked against the toolkit code and AmneziaVPN 5.1.0.6.
Supported server releases are **Ubuntu 22.04, 24.04 and 26.04 LTS amd64**.
Other releases and architectures are not supported. `amnezia-awg2` in `.vpn` is a client
format identifier, not a requirement for Docker or protocol version 2.

## Primary sources

- [AmneziaWG](https://docs.amnezia.org/documentation/amnezia-wg/).
- [Split tunneling](https://docs.amnezia.org/ru/documentation/instructions/vpn-split-tunneling/).
- [Client 5.1.0.6 source](https://github.com/amnezia-vpn/amnezia-client/tree/5.1.0.6).
- [Import and decoding](https://github.com/amnezia-vpn/amnezia-client/blob/5.1.0.6/client/core/controllers/selfhosted/importController.cpp).
- [AWG/last_config fields](https://github.com/amnezia-vpn/amnezia-client/blob/5.1.0.6/client/core/models/protocols/awgProtocolConfig.cpp).
- [Cache reuse](https://github.com/amnezia-vpn/amnezia-client/blob/5.1.0.6/client/core/controllers/selfhosted/installController.cpp).
- [Endpoint and server-address exclusion](https://github.com/amnezia-vpn/amnezia-client/blob/5.1.0.6/client/mozilla/localsocketcontroller.cpp).
- [CIDR-mask loss in hostname report](https://github.com/amnezia-vpn/amnezia-client/issues/2939).
- [Android ProtocolConfig](https://github.com/amnezia-vpn/amnezia-client/blob/dev/client/android/protocolApi/src/main/kotlin/ProtocolConfig.kt): a mutable branch; behavior depends on version.
- [Android Binder and TransactionTooLargeException](https://developer.android.com/reference/android/os/TransactionTooLargeException).
- [AdGuard application routing and filtering](https://adguard.com/kb/adguard-for-windows/app-management/).

## Address snapshots

- RU IPv4: [RIPEstat](https://stat.ripe.net/data/country-resource-list/data.json?resource=RU&v4_format=prefix), query_time **2026-11-07**.
- Protected providers: [Google](https://www.gstatic.com/ipranges/goog.json), [Cloudflare](https://www.cloudflare.com/ips-v4), [Telegram](https://core.telegram.org/resources/cidr.txt); snapshots from 8–9 November 2026, 154 collapsed IPv4 prefixes.
- Services catalog: [lib4u/amnezia-tunneling-ru](https://github.com/lib4u/amnezia-tunneling-ru), commit `64e090efba761ba11dd618e70dc7da1c8a345235`, file `amnezia.json`, SHA256 `16e78eeac83c64e34311d165ed7f50f5b93f2c64651479af3c5653f6705213ec`.
- DNS supplement: [Google Public DNS JSON API](https://developers.google.com/speed/public-dns/docs/doh/json), snapshot **2026-11-09T02:07:47Z**. A records were found for 15 of 22 missing families.

`data/ru-networks.txt` has 8678 collapsed RU/local prefixes;
`data/protected-vpn-networks.txt` has provider ranges;
`data/service-addresses.txt` contains service addresses;
`data/service-roots.txt` lists 86 selected families. These are generic data,
not configured VPN nodes. Offline generation without extra protected IPs
reproduces the supplied JSON. Online generation fetches fresh data and prints
the catalog identifier. [Coverage policy, added bypass and hashes](lists.md).

## AWG 3.1 binary bundle

`servers/build-native.sh` builds on separate Ubuntu 22.04 amd64:

- [amneziawg-go](https://github.com/amnezia-vpn/amneziawg-go/tree/1b86b2ae0e493e7ea93f8c1a0f0cb6735b1551f1), commit `1b86b2ae0e493e7ea93f8c1a0f0cb6735b1551f1`;
- [amneziawg-tools](https://github.com/amnezia-vpn/amneziawg-tools/tree/ee0f0a9aa34ff0a0da4b3433b9512781cfe02843), commit `ee0f0a9aa34ff0a0da4b3433b9512781cfe02843`;
- Go 1.25.12 from go.dev, verified using a pinned SDK SHA256.

The bundle manifest records provenance/hashes. Licenses and corresponding
GPL tool source are included; keep them when redistributing the bundle.
No compiler is installed on the VPS.

Parameter generation follows [AwgInstaller](https://github.com/amnezia-vpn/amnezia-client/blob/5.1.0.6/client/core/installers/awgInstaller.cpp)
and [protocolConstants.h](https://github.com/amnezia-vpn/amnezia-client/blob/5.1.0.6/client/core/utils/constants/protocolConstants.h).
The export schema follows [SelfHostedUserServerConfig](https://github.com/amnezia-vpn/amnezia-client/blob/5.1.0.6/client/core/models/selfhosted/selfHostedUserServerConfig.cpp),
format_version=1, without SSH access. Official `awg` generates keys.

## Xray REALITY

- [Xray-core 26.10.21](https://github.com/XTLS/Xray-core/releases/tag/v26.10.21): pinned official linux-amd64 ZIP.
- [This version's source](https://github.com/XTLS/Xray-core/tree/v26.10.21), including REALITY and freedom configuration.
- [Original REALITY description](https://github.com/XTLS/REALITY).
- [Official REALITY documentation](https://xtls.github.io/en/config/transports/reality.html).
- [Third-party Xray import in Amnezia 5.1.0.6](https://github.com/amnezia-vpn/amnezia-client/blob/5.1.0.6/client/core/controllers/selfhosted/importController.cpp).

Upstream and minimal toolkit bundle hashes are in [xray.md](xray.md) and its
`dist/xray-native-linux-amd64.tar.gz` manifest. MPL 2.0 and the exact source
tag URL are included. This configuration needs no geoip/geosite databases,
so they are omitted. `servers/fetch-xray.py` verifies the upstream ZIP; the
installer checks the toolkit bundle against a pin in code.

## Verification

Automated tests cover synthetic profile conversion, preservation of keys and
administrator SSH host, refusal to overwrite, list coverage/protection,
route calculations, archives, installer checks, SSH host keys and deploy
failure order. They do not substitute for real client network tests.

Installation, traffic, peer addition, reboot and restore were exercised on
Ubuntu 22.04 VMs with 1 vCPU / 1 GiB each; a separate two-server lab checked
deploy and authenticated traffic through the relay. [Earlier exit report](validation-native.md),
[Ubuntu 22.04 three-mode report](validation-protocols.md).
The later [LTS cycle](validation-lts.md) tested all three modes on fresh
Ubuntu 24.04 and 26.04 VMs with the same 1 vCPU / 1 GiB allocation, including
sudo-rs, Python 3.12/3.14, cold boots and restore.

Native AWG and Xray carried real traffic. AmneziaVPN 5.1.0.6 Linux in a
separate VM imported AWG `.vpn`, Xray JSON and VLESS URI, storing appropriate
containers/credentials without a GUI VPN connection. These exports were not
imported on every physical Windows/macOS/Android/iOS device. The AdGuard note
is one manual observation, not a compatibility guarantee for all versions.
IPv6 egress is absent; all DNS/DoH/KillSwitch combinations were not tested.
Short memory measurements do not establish maximum throughput, multi-day
stability or evasion of a particular DPI implementation.
