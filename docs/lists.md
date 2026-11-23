# Split-tunneling lists

[Русский](ru/lists.md) · [Project home](../README.md)

Import one of these files to send selected IPv4 traffic through your ISP.

| File | Traffic sent directly | IPv4 prefixes |
| --- | --- | ---: |
| [`ru-direct.amnezia.json`](../ru-direct.amnezia.json) | All Russian IPv4 allocations from the RIPE snapshot, local networks and some addresses outside those ranges. | 1,097 |
| [`ru-services.amnezia.json`](../ru-services.amnezia.json) | Local networks and Russian allocations that contain addresses of selected services. | 77 |

The shorter list covers addresses associated with 86 service families, including Yandex, VK, banks and public services. It omits their addresses outside Russian allocations. The full list adds about 111 million other IPv4 addresses to keep the route count down on older Android clients. Use the short list when you want fewer destinations outside the VPN.

## Import a list

In the app’s website split-tunneling settings, choose the mode that sends listed destinations outside the VPN. Import one JSON file with **Replace list**. With the VPN on, verify that a listed destination sees your ISP’s IP and a destination routed through the VPN sees B’s IP. If the app stops connecting after import, disable website split tunneling and try again. The `ru-direct` list was tested on a phone with a working VPN connection.

## Refresh both files

Install Python 3.10 or newer. In the COLDWIRE panel, choose **12 Update split-tunneling lists**. You can use this option before setting up any servers.

To run the generator on its own, download `COLDWIRE-RU-Lists.zip` and extract it. On Windows, open `COLDWIRE-Lists.cmd`. On Linux, open a terminal in the extracted folder and run `bash COLDWIRE-Lists.sh`. [GitHub Releases](https://github.com/bgunn9in/coldwire/releases/latest)

By default, the generator fetches current data and prints the path to a new timestamped folder under `generated/`. It writes both `ru-direct.amnezia.json` and `ru-services.amnezia.json`. Add `--output` to choose a new folder or `--offline` to regenerate the bundled lists from the snapshots in `data/`.

| Run with offline snapshots | Command |
| --- | --- |
| Windows panel | `COLDWIRE-Admin.cmd update-lists --offline` |
| Linux panel | `bash COLDWIRE-Admin.sh update-lists --offline` |
| Windows standalone | `COLDWIRE-Lists.cmd --offline` |
| Linux standalone | `bash COLDWIRE-Lists.sh --offline` |

Use `--vpn-only IPV4` for an individual address you need to keep in the tunnel. Repeat the option for additional addresses. `--entry IPV4` and `--exit IPV4` protect the relay addresses in the same way. The generator stops if an address conflicts with the exact Russian or local source ranges. [Data sources and route counts](sources.md)
