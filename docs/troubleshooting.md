# Verification and troubleshooting

English | [Русский](ru/troubleshooting.md)

Replace `ENTRY_IPV4`/`EXIT_IPV4` and example interface `ens3` with your own.
Do not switch the only working VPN for diagnosis. Use a spare device with
separate access and retain a direct B profile. The installers require clean
Ubuntu 22.04, 24.04 or 26.04 LTS amd64 servers. They do not repair existing
deployments.

## Symptoms

| Observation | Check |
|---|---|
| Ubuntu 26.04 image cannot boot / illegal instruction | Check amd64 versus amd64v3 and the virtual CPU features; see [LTS report](validation-lts.md) |
| Direct B works, A does not | A's Endpoint, selected TCP/UDP port, provider firewall, forwarding/NAT and capture on A |
| Works without exclusions, fails with list | Bypass mode, Replace list, route count; try `ru-services` |
| UDP443 fails with a local filter | Compare 32497 on a test device; do not regenerate keys |
| Connected but websites fail | Handshake/transfer, DNS, MTU, client routes and IPv6 |
| Administrator functions missing | Export type and preserved top-level B management host |
| Configuration changes produce a direct connection | Application recreated `last_config`; convert a fresh export again |

Using one peer on two devices moves its Endpoint. Issue separate access.
Regenerating B's keys invalidates previously issued profiles.

## Windows and client checks

```powershell
Find-NetRoute -RemoteIPAddress ENTRY_IPV4
Find-NetRoute -RemoteIPAddress 77.88.55.88
Test-NetConnection EXIT_IPV4 -Port 22
```

The route to A must use the physical connection. With RU exclusions, the
checked Yandex address should also route directly. `Test-NetConnection -Port`
checks **TCP**, not AWG UDP. Working SSH or a TCP32497 check does not prove AWG.

Open `https://api.ipify.org` without another proxy: expect B's IPv4. Yandex
Internetometer should see the ISP address when its destination is excluded.
Check actual traffic, not only the Connected indicator.
[AdGuard and port comparison](windows-admin-port-diagnosis.md).

## Entry A

Read-only commands:

```bash
sysctl net.ipv4.ip_forward
systemctl status blackice-relay.service --no-pager
systemctl is-enabled blackice-relay.service
sudo nft list table ip blackice_relay
ip route get EXIT_IPV4
journalctl -u blackice-relay.service -n 40 --no-pager
systemctl list-timers --all --no-pager
```

Expect forwarding=1, active/exited and enabled, DNAT to the selected B port,
and masquerade for DNAT only. A NAT counter normally records the first
packet of a new conntrack flow, not every packet. Inspect FORWARD counters
and a short header capture; tcpdump is installed separately:

```bash
sudo timeout 20 tcpdump -ni ens3 -nn 'udp and (port 443 or port 32497)'
```

Adapt the filter for other ports or TCP. If traffic reaches A but is not
forwarded to B, inspect A's rules and routes. If nothing reaches A, check
the client Endpoint and filter, local router and network, and provider firewall. No relay
listener in `ss -lunp` is normal.

## Exit B

For this toolkit's native AWG:

```bash
systemctl status awg-relay-kit-exit.service --no-pager
sudo /usr/local/libexec/awg-relay-kit/awg show awg0
sudo /usr/local/libexec/awg-relay-kit/awg show awg0 latest-handshakes
sudo /usr/local/libexec/awg-relay-kit/awg show awg0 endpoints
sudo /usr/local/libexec/awg-relay-kit/awg show awg0 transfer
sudo nft list table ip awg_exit
```

Expect a fresh handshake and bidirectional transfer. Via the relay, B sees A
as the peer Endpoint; the NAT source port can vary. Seeing the real client
address means direct access. If packets arrive but no handshake occurs,
compare registered peer, keys/PSK and AWG parameters with a working direct profile.

Do not publish `showconf`, `dump`, server.json, `.vpn` or payload captures:
they can expose secrets. Redact public peer keys and deployment addresses in
shared logs too. [Native service design](native-server.md).

## DNS, IPv6 and MTU

Check ordinary DNS and browser DoH separately. A website bypass does not
automatically bypass its DNS queries. Snapshots protect 1.1.1.1, 1.0.0.1 and
8.8.8.8 from bypass.

```bash
curl --noproxy '*' -4 https://api.ipify.org
curl --noproxy '*' -6 --max-time 10 https://api64.ipify.org
```

IPv4 should match B. IPv6 egress is not implemented. If the second request
shows the ISP address, inspect client IPv6/KillSwitch policy. A virtual IPv6
address alone does not prove IPv6 connectivity through B.

If short requests succeed but large pages hang, check MTU on a test client,
starting with its profile value. Native exports use MTU1280; conversion
preserves the source export's MTU.

Russian services may use foreign CDNs absent from `ru-services`. `ru-direct`
covers RU more broadly but deliberately adds foreign bypass. Choose a policy
instead of merging them. Save logs using the [official Amnezia procedure](https://docs.amnezia.org/ru/documentation/instructions/logging/)
and remove access credentials, node addresses and user data before sharing.

## REALITY

```bash
systemctl status awg-relay-kit-xray.service --no-pager
journalctl -u awg-relay-kit-xray.service -n 40 --no-pager
sudo ss -ltnp
```

B needs a listener on the selected TCP port; A needs none. Via A, established
connections on B show source A. An ordinary TLS handshake or open TCP port
does not prove VLESS egress: test an actual client with correct UUID, shortId,
SNI, REALITY key and Vision.

| Phase/symptom | Check |
|---|---|
| `XRAY_PREFLIGHT` | Supported Ubuntu LTS amd64, assigned IP, free TCP port, clean server |
| `XRAY_TLS_TARGET` | B can reach target, valid certificate and TLS1.3/h2/X25519; optionally use `--reality-target` |
| `XRAY_BINARY_INSTALL` | Bundle/pinned SHA, disk space, `/usr/local/libexec` permissions |
| `XRAY_ACTIVATION` | systemd journal, executable permissions, TCP port, LoadCredential and listener readiness |
| Active service, failing client | Matching SNI/UUID/shortId/key/port, clocks, firewall and client network |
| Some dual-stack sites fail | Preserve server DNS `UseIPv4` and freedom sockopt `domainStrategy: UseIPv4` |

Ubuntu 22.04's systemd 249 receives the credential path using
`${CREDENTIALS_DIRECTORY}`, not `%d`. DynamicUser needs traversal of
`/usr/local/libexec` and executable reads, not direct access to private state.
New binary directories are 0755; an existing private shared parent is rejected
instead of weakened. Never make `/etc/awg-relay-kit-xray` world-readable.

REALITY uses X25519. Python 3.10 `ssl.set_ecdh_curve('X25519')` is unsuitable
for testing that group on stock Ubuntu 22.04; use OpenSSL:

```bash
openssl s_client -4 -connect TARGET_HOST:443 -servername TARGET_HOST -tls1_3 -groups X25519 -alpn h2 -verify_hostname TARGET_HOST -verify_return_error -no_ign_eof </dev/null
```

Do not publish private config/server.json or client JSON/URI. Running
`xray run -test -config ...` as root checks syntax, not DynamicUser access or
client connectivity. Diagnose services independently in `both`; Xray restart
does not require AWG restart. [Xray maintenance](xray.md).
