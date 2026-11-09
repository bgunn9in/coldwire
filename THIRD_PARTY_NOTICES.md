# Licenses and third-party materials

The [MIT license](LICENSE) covers the original COLDWIRE scripts, tests,
documentation and artwork. It does not relicense
bundled third-party software or upstream address data. Keep upstream notices
when redistributing.

| Material | License / provenance |
|---|---|
| `amneziawg-go` | MIT; the original notice is `LICENSE.amneziawg-go` inside the AWG bundle |
| `amneziawg-tools` | GNU GPL version 2; `COPYING.amneziawg-tools` and the corresponding source archive are inside the AWG bundle |
| Xray-core | Mozilla Public License 2.0; `LICENSE` and a manifest linking the exact source tag are inside the Xray bundle |
| Address snapshots under `data/` and generated RU lists | Derived from the upstream sources documented in [sources](docs/sources.md); not relicensed under the project's MIT license |
| `assets/coldwire-logo.png`, `assets/coldwire-header.svg`, `assets/coldwire-topology.svg`, `assets/coldwire-topology.ru.svg` | Original COLDWIRE project artwork, MIT; [provenance](assets/README.md) |

The installed binaries are unmodified builds of their documented upstream
components. Version pins, source links and SHA256 checksums are preserved in
the bundle manifests. AWG tool source is included so that redistributing its
binary does not discard the corresponding source. Xray's exact source version
is available at the manifest's source URL.

For data provenance, see [English](docs/sources.md) or
[Russian](docs/ru/sources.md). The logo was created for COLDWIRE; it is not an
upstream VPN application's logo and does not imply endorsement by upstreams.
