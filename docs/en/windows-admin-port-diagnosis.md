# Windows, AdGuard and UDP-port compatibility

[Русский](../windows-admin-port-diagnosis.md) · **English**

This records one configuration, not universal compatibility of AdGuard and
AmneziaVPN versions. It contains no deployment-node addresses, exports, logs
or working-installation details.

## Observed conflict

A manual test with AmneziaVPN 5.1.0.6 and AdGuard for Windows 8.0.4 gave these
results for the original administrator AWG profile:

| Entry UDP port | AdGuard protection | Result |
|---|---|---|
| 443 | On | Does not connect |
| 443 | Off | The same profile connects |
| 32497 | On | Connects |

A phone on the same network connected through 443. Administrator profiles
for 443/32497 had identical keys, AWG parameters and SSH access; only client
port fields and labels differed. This points to a local filtering conflict
on 443, not a requirement to change profile role or keys.

The particular AdGuard feature was not identified. UDP443/QUIC processing is
a hypothesis; no simultaneous before/after-filter capture was collected.
Do not call every 443 failure ISP blocking or an AdGuard bug without comparison.

AdGuard's service/driver may remain Running with protection disabled. That
status does not show whether traffic processing is enabled. The [AdGuard
documentation](https://adguard.com/kb/adguard-for-windows/app-management/)
distinguishes application routing through AdGuard from filtering itself.

## One default for all client OSes

**32497/UDP is the common default** for Windows, macOS, Android and iPhone.
Neither converter nor deploy detects the OS or AdGuard. This keeps one server
design and AWG parameters without special AdGuard rules in the tested setup.

It does not promise compatibility with every filter/operator. Conversion
preserves obfuscation settings; port 443 does not turn AWG into HTTPS. If
443 is mandatory, separately test client filters and VPN processes. A server
change cannot recover a packet discarded by a local filter.

## Reproducing the comparison

Retain a working profile. Use a test device with a separate peer; never run
one peer on the main and test devices simultaneously. Compare two profiles
differing only in port, on one network with identical bypass/protection
settings. Collect logs for the same interval and short UDP header captures
on the client and entry.

`Test-NetConnection -Port` checks TCP, not UDP. A random UDP packet does not
test an AWG handshake, because unauthenticated packets are silently discarded.

A separately reported [SockFilter / Winsock 10014 conflict](https://github.com/amnezia-vpn/amnezia-client/issues/3048)
involves another driver, `adgnetworksockdrv.sys`, and `wsasendmsg`/`wsarecvmsg`
errors. This observation used WFP (`adgnetworkwfpdrv.sys`) without those errors.
Do not transfer another setup's diagnosis or driver-switching advice without
matching symptoms.
