# Data and upstream software

[Русский](ru/sources.md) · [Project home](../README.md)

## Address data

- Russian IPv4 allocations came from [RIPEstat](https://stat.ripe.net/data/country-resource-list/data.json?resource=RU&v4_format=prefix) on 7 November 2026.
- The provider snapshots came from [Google](https://www.gstatic.com/ipranges/goog.json), [Cloudflare](https://www.cloudflare.com/ips-v4) and [Telegram](https://core.telegram.org/resources/cidr.txt) on 8 and 9 November 2026.
- The service catalog uses `amnezia.json` from [lib4u/amnezia-tunneling-ru](https://github.com/lib4u/amnezia-tunneling-ru/tree/64e090efba761ba11dd618e70dc7da1c8a345235). The snapshot also uses A records queried through [Google Public DNS](https://developers.google.com/speed/public-dns/docs/doh/json) on 9 November 2026.

The source snapshots are in [`data/`](../data/). The generator collapses overlapping ranges and keeps all Russian and local prefixes in `ru-direct`. To reduce the complement route table, it includes some other IP ranges in the bypass list. The supplied snapshot adds 111,284,160 IPv4 addresses and yields 2,004 routes in the older Android route model. `ru-services` yields 751 routes in the same model. These counts describe the generated configurations. [List options and update commands](lists.md)

The `ru-direct` budget is 2,004 routes for Android 10–12, including one for IPv6. The generator removes IPv4 loopback before counting routes. It reserves the VPN prefixes that carry protected addresses, then fills the remaining slots with the largest eligible IPv4 prefixes. Each prefix costs one route, so this keeps the most addresses in the VPN within the budget. `ru-services` merges adjacent ranges wherever they can share a CIDR without expanding coverage.

## AmneziaWG 3.1 and SPA

The native bundle includes [amneziawg-go at `1b86b2a`](https://github.com/amnezia-vpn/amneziawg-go/tree/1b86b2ae0e493e7ea93f8c1a0f0cb6735b1551f1) and [amneziawg-tools at `ee0f0a9`](https://github.com/amnezia-vpn/amneziawg-tools/tree/ee0f0a9aa34ff0a0da4b3433b9512781cfe02843). The version manifest, licenses and corresponding source for amneziawg-tools are inside the bundle under `dist/`. [Build script](../servers/build-native.sh) · [Third-party notices](../THIRD_PARTY_NOTICES.md)

The native installer follows the AmneziaWG parameters and export format in [AmneziaVPN 5.1.0.6](https://github.com/amnezia-vpn/amnezia-client/tree/5.1.0.6). In `.vpn` files, `amnezia-awg2` is the client’s configuration identifier. The installer runs AmneziaWG under systemd without Docker. The COLDWIRE fork adds the SPA client code. [SPA server source](../servers/spa/) · [VPN client source](https://github.com/bgunn9in/COLDWIRE-amnezia-client)
