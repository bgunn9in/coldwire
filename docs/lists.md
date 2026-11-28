# Split-tunneling lists

[Русский](ru/lists.md) · [Project home](../README.md)

Import one of these files to send selected IPv4 traffic through your ISP.

| File | Traffic sent directly | Bundled IPv4 prefixes |
| --- | --- | ---: |
| [`ru-direct.amnezia.json`](../ru-direct.amnezia.json) | All Russian IPv4 allocations from the RIPE snapshot, local networks and some addresses outside those ranges. | 1,097 |
| [`ru-services.amnezia.json`](../ru-services.amnezia.json) | Local networks and Russian allocations that contain addresses of selected services. | 77 |

The shorter list covers addresses associated with 86 service families, including Yandex, VK, banks and public services. It omits their addresses outside Russian allocations. The full list adds about 111 million other IPv4 addresses to keep the route count down on older Android clients. Use the short list when you want fewer destinations outside the VPN.

## Import a list

In builds of COLDWIRE with the in-app list menu, disconnect the VPN and open **Connection → Site-based split tunneling → ⋯**. Choose **Russian services** or **Russian IPv4 ranges**, then confirm the replacement. The app offers its bundled copy if the download fails. [Client guide](https://github.com/bgunn9in/COLDWIRE-amnezia-client/blob/feature/spa-admission/docs/spa.md)

In the app’s site-based split-tunneling settings, choose **Directly** and import one JSON file with **Replace site list**. With the VPN on, verify that a listed destination sees your ISP’s IP and a destination routed through the VPN sees B’s IP. If the app stops connecting after import, disable site-based split tunneling and try again. The `ru-direct` list was tested on a phone with a working VPN connection.

## Refresh both files

The GitHub Actions workflow **Refresh Russian site lists for COLDWIRE** runs weekly and can also be run manually. It publishes both JSON files together to the `ru-lists` branch. If a source fails, the previous pair remains available.

Install Python 3.10 or newer. For the interactive panel on Ubuntu or Debian, install `python3-venv` too. Open the panel and choose **12 Update split-tunneling lists**. Use **1** for current data or **2** for the bundled snapshots. You can do this before you set up your servers.

To run the generator on its own, download `COLDWIRE-RU-Lists.zip` and extract it. On Windows, open `COLDWIRE-Lists.cmd`. On Linux, open a terminal in the extracted folder and run `bash COLDWIRE-Lists.sh`. [GitHub Releases](https://github.com/bgunn9in/coldwire/releases/latest)

The generator fetches current data, writes both JSON files to a new timestamped folder under `generated/` and prints the path. Add `--output` to choose a new folder. With `--offline`, the generator uses the snapshots in `data/` and reproduces the bundled files.

If an online source fails, the panel names it and offers to try again with the bundled snapshots. At the command line, rerun with `--offline`. Earlier output folders are kept for reuse.

| Run with offline snapshots | Command |
| --- | --- |
| Windows panel | `COLDWIRE-Admin.cmd update-lists --offline` |
| Linux panel | `bash COLDWIRE-Admin.sh update-lists --offline` |
| Windows standalone | `COLDWIRE-Lists.cmd --offline` |
| Linux standalone | `bash COLDWIRE-Lists.sh --offline` |

### Compare with earlier lists

When the panel asks for a comparison folder, enter the folder containing both previous JSON files. Press Enter to skip. At the command line, pass `--compare-with DIRECTORY`. The generator prints the RIPE snapshot date and, for each list, the number of IPv4 prefixes added and removed and the total route count for older versions of Android. Check the summary before importing the JSON you want.

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

### Source selection and offline recovery

We repeated the five-VM matrix with the new menu. Each guest ran the standalone generator with live data and with bundled snapshots, then repeated both modes in the panel. A blocked connection to RIPEstat triggered the offline prompt. After confirmation, the panel wrote a new pair that matched the bundled files. It also reported zero prefix changes when comparing the two offline pairs. The baseline files kept their original checksums.

GitHub Actions built one pair of ZIPs. The Windows and Linux jobs each unpacked the archives and ran the launchers to reproduce both bundled lists. [GitHub Actions run](https://github.com/bgunn9in/coldwire/actions/runs/45282319496)

## Android import test

We imported both fresh lists in AmneziaVPN 5.1.1.10 on an Android 10 x86-64 emulator connected to a local AmneziaWG 3.1 guest. Each time we chose **Directly** and used **Replace site list**. A local HTTP server returned the source IP of each request. For both lists, it saw the direct path on the excluded address and the VPN peer address on the control address.
