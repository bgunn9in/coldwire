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

Run the generator with Python 3.10 or newer. The output directory must be new.

```bash
python3 update_lists.py --output generated/fresh-lists
python3 update_lists.py --offline --output generated/snapshot-lists
```

The first command fetches current data. The second uses the snapshots in `data/` and reproduces the two bundled JSON files. Each command writes both lists. On Windows, substitute `python` for `python3` if that is the name of your interpreter.

Use `--vpn-only IPV4` for an individual address you need to keep in the tunnel. Repeat the option for additional addresses. `--entry IPV4` and `--exit IPV4` protect the relay addresses in the same way. The generator stops if an address conflicts with the exact Russian or local source ranges. [Data sources and route counts](sources.md)
