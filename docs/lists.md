# Split-tunneling lists

[Русский](ru/lists.md) · [Project home](../README.md)

Import one of these files to send selected IPv4 traffic through your ISP.

| File | Traffic sent directly | Bundled IPv4 prefixes |
| --- | --- | ---: |
| [`ru-direct.amnezia.json`](../ru-direct.amnezia.json) | All Russian IPv4 allocations from the RIPE snapshot, local networks and some addresses outside those ranges. | 1,097 |
| [`ru-services.amnezia.json`](../ru-services.amnezia.json) | Local networks and Russian allocations that contain addresses of selected services. | 77 |

The shorter list covers addresses associated with 86 service families, including Yandex, VK, banks and public services. It omits their addresses outside Russian allocations. The full list adds about 111 million other IPv4 addresses to keep the route count down on older Android clients. Use the short list when you want fewer destinations outside the VPN.

## Import a list

In the app’s website split-tunneling settings, choose the mode that sends listed destinations outside the VPN. Import one JSON file with **Replace list**. With the VPN on, verify that a listed destination sees your ISP’s IP and a destination routed through the VPN sees B’s IP. If the app stops connecting after import, disable website split tunneling and try again. The `ru-direct` list was tested on a phone with a working VPN connection.

## Refresh both files

Install Python 3.10 or newer. For the interactive panel on Ubuntu or Debian, install `python3-venv` too. Open the panel and choose **12 Update split-tunneling lists**. This works before you set up your servers.

To run the generator on its own, download `COLDWIRE-RU-Lists.zip` and extract it. On Windows, open `COLDWIRE-Lists.cmd`. On Linux, open a terminal in the extracted folder and run `bash COLDWIRE-Lists.sh`. [GitHub Releases](https://github.com/bgunn9in/coldwire/releases/latest)

The generator fetches current data, writes both JSON files to a new timestamped folder under `generated/` and prints the path. Add `--output` to choose a new folder. With `--offline`, the generator uses the snapshots in `data/` and reproduces the bundled files.

| Run with offline snapshots | Command |
| --- | --- |
| Windows panel | `COLDWIRE-Admin.cmd update-lists --offline` |
| Linux panel | `bash COLDWIRE-Admin.sh update-lists --offline` |
| Windows standalone | `COLDWIRE-Lists.cmd --offline` |
| Linux standalone | `bash COLDWIRE-Lists.sh --offline` |

Use `--vpn-only IPV4` for an individual address you need to keep in the tunnel. Repeat the option for additional addresses. `--entry IPV4` and `--exit IPV4` protect the relay addresses in the same way. The generator stops if an address conflicts with the exact Russian or local source ranges. [Data sources and route counts](sources.md)

## Linux test results

We tested the published archives in five local amd64 VMs under QEMU/WHPX, each with one vCPU and 1 GiB of RAM. In each VM we ran `COLDWIRE-Lists.sh` once with `--offline` and once with live data. We also ran `COLDWIRE-Admin.sh` and chose **12** before setting up any servers. [Release used for testing](https://github.com/bgunn9in/coldwire/releases/tag/spa-panel-5e0d77838652)

| Distribution | Python | Standalone, offline and online | Panel menu 12 |
| --- | --- | --- | --- |
| Ubuntu 22.04.5 LTS | 3.10.12 | Passed | Passed |
| Ubuntu 24.04.5 LTS | 3.12.3 | Passed | Passed |
| Ubuntu 26.04.1 LTS | 3.14.4 | Passed | Passed |
| Debian 12 | 3.11.2 | Passed | Passed |
| Debian 13 | 3.13.5 | Passed | Passed |

All 30 files passed JSON format and legacy Android route-count checks. On every VM, the two offline files matched the bundled files byte for byte.

The live runs used the November 22, 2026 RIPE snapshot and service catalog commit `d49d6fb2ce27417a03169c3cf365fabfd3f7932a`. They produced 1,095 prefixes in the full list and 76 in the compact list. On Ubuntu 24.04, one prefix in the compact list differed between the two runs. The standalone run yielded 740 legacy Android routes, and menu 12 yielded 736. The generator looks up service addresses in DNS, so the compact list can vary between live runs.

### SHA-256

| Output | Legacy Android routes | SHA-256 |
| --- | ---: | --- |
| Offline `ru-direct.amnezia.json` | 2,004 | `10706c300dbd4122bdaacb166ecb301377bca9734a29aa901923699b29dd4a51` |
| Offline `ru-services.amnezia.json` | 751 | `7ecaa6a95b8e12ffe72b5442723606b7b65cd1f2d6e4638cfc6be3a65e015bb1` |
| Live `ru-direct.amnezia.json` | 2,004 | `ae337cab00517c0a37bce32b095d1899fafc6d4763dd423ee4676bedd5fd168b` |
| Live `ru-services.amnezia.json` | 736 | `7cbda80775ec6f945f54f3f0499007cc5051212e5f9eb43edd7be549ab36f735` |
| Live `ru-services.amnezia.json`, standalone on Ubuntu 24.04 | 740 | `58f740a111a56a3fd0e6ecd6a88f4cb438cd936669084004c638964aae16e2b8` |
