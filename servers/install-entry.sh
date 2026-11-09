#!/usr/bin/env bash
# Entry relay for a clean Ubuntu 22.04, 24.04 or 26.04 LTS amd64 server.
set -euo pipefail
export LC_ALL=C
[[ $EUID == 0 ]] || { echo 'Run as root'; exit 1; }
[[ $# -ge 2 && $# -le 6 ]] || { echo 'Usage: bash install-entry.sh ENTRY_IPV4 EXIT_IPV4 [UDP_PORTS=32497 or -] [UDP_EXIT=32497] [TCP_ENTRY=0] [TCP_EXIT=443]'; exit 1; }
entry=$1; destination=$2; ports=${3:-32497}; destination_port=${4:-32497}
tcp_entry=${5:-0}; tcp_exit=${6:-443}
python3 - "$entry" "$destination" "$ports" "$destination_port" "$tcp_entry" "$tcp_exit" <<'PY'
import ipaddress,os,sys
a,b,ports,port,tcp,tcp_exit=sys.argv[1:]
def valid(value):
    address=ipaddress.IPv4Address(value)
    private=os.environ.get('AWG_ALLOW_PRIVATE_ENDPOINT')=='1' and any(address in ipaddress.IPv4Network(n) for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16'))
    return address.is_global and not address.is_multicast or private
if not valid(a) or not valid(b) or a == b:
    raise ValueError('Different public IPv4 addresses required; private lab addresses need AWG_ALLOW_PRIVATE_ENDPOINT=1')
udp=[] if ports=='-' else ports.split(',')
if not all(p.isdecimal() and 1 <= int(p) <= 65535 and str(int(p)) == p for p in udp+[port,tcp_exit]) or len(set(udp)) != len(udp) or not tcp.isdecimal() or not 0<=int(tcp)<=65535 or str(int(tcp))!=tcp or not udp and tcp=='0':
    raise ValueError('Invalid or duplicate UDP ports')
PY
source /etc/os-release
[[ $ID == ubuntu && ( $VERSION_ID == 22.04 || $VERSION_ID == 24.04 || $VERSION_ID == 26.04 ) && $(uname -m) == x86_64 ]] || { echo 'Ubuntu 22.04, 24.04 or 26.04 LTS amd64 required'; exit 1; }
[[ -d /run/systemd/system ]] || { echo 'systemd is required'; exit 1; }
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
[[ -f $script_dir/rollback-entry.sh && -f $script_dir/confirm-entry.sh ]] || { echo 'Copy the whole servers directory'; exit 1; }
[[ ! -e /var/lib/awg-relay-kit && ! -e /etc/blackice-relay.nft && ! -e /etc/systemd/system/blackice-relay.service && ! -e /etc/sysctl.d/90-blackice-relay.conf ]] || { echo 'Relay already exists; installation refused. Use documented maintenance/rollback.'; exit 1; }
[[ $(sysctl -n net.ipv4.ip_forward) == 0 ]] || { echo 'Existing forwarding detected; dedicated clean entry required'; exit 1; }
if command -v docker >/dev/null && [[ -n $(docker ps -q) ]]; then echo 'Running containers detected; installation refused'; exit 1; fi
if command -v ufw >/dev/null && ufw status | grep -q '^Status: active'; then echo 'Active UFW detected; installation refused'; exit 1; fi
if command -v nft >/dev/null && [[ -n $(nft list tables) ]]; then echo 'Existing nftables tables detected; installation refused'; exit 1; fi
iface=$(ip -j route get "$destination" | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["dev"])')
[[ $iface =~ ^[a-zA-Z0-9_.-]+$ ]] || { echo 'Invalid interface'; exit 1; }
ip -j address show dev "$iface" | python3 -c 'import json,sys; a=json.load(sys.stdin); sys.exit(0 if any(i.get("local")==sys.argv[1] for x in a for i in x["addr_info"]) else "Entry IPv4 is not assigned to the WAN interface")' "$entry"
IFS=',' read -ra checked_ports <<< "$ports"
for checked_port in "${checked_ports[@]}"; do
    [[ $checked_port != - ]] || continue
    [[ -z $(ss -H -lun "sport = :$checked_port") ]] || { echo 'An entry UDP port is occupied'; exit 1; }
done
if [[ $tcp_entry != 0 ]]; then
    [[ -z $(ss -H -ltn "sport = :$tcp_entry") ]] || { echo 'An entry TCP port is occupied (possibly SSH)'; exit 1; }
fi
if [[ ${AWG_PREFLIGHT_ONLY:-0} == 1 ]]; then echo 'Entry preflight passed; no installation performed'; exit 0; fi
# No upgrades, no global ruleset flush, no SSH/INPUT policy changes.
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends nftables
[[ -z $(nft list tables) ]] || { echo 'nftables is not empty after dependency installation; refused'; exit 1; }
install -d -m 700 /var/lib/awg-relay-kit
printf '0\n' > /var/lib/awg-relay-kit/old-ip-forward
install -m 700 "$script_dir/rollback-entry.sh" /var/lib/awg-relay-kit/rollback-entry.sh
install -m 700 "$script_dir/confirm-entry.sh" /var/lib/awg-relay-kit/confirm-entry.sh
armed=0
trap 'if (( armed )); then bash /var/lib/awg-relay-kit/rollback-entry.sh; fi' ERR
systemd-run --unit=blackice-relay-safety --on-active=5m --timer-property=AccuracySec=1s /bin/bash /var/lib/awg-relay-kit/rollback-entry.sh
armed=1
udp_pre=''; udp_post=''; udp_forward=''; tcp_pre=''; tcp_post=''; tcp_forward=''
if [[ $ports != - ]]; then
    udp_pre="iifname \"$iface\" ip daddr $entry udp dport {$ports} counter dnat to $destination:$destination_port"
    udp_post="oifname \"$iface\" ip daddr $destination udp dport $destination_port ct status dnat counter masquerade"
    udp_forward="iifname \"$iface\" oifname \"$iface\" ip daddr $destination udp dport $destination_port ct status dnat counter accept"
fi
if [[ $tcp_entry != 0 ]]; then
    tcp_pre="iifname \"$iface\" ip daddr $entry tcp dport $tcp_entry counter dnat to $destination:$tcp_exit"
    tcp_post="oifname \"$iface\" ip daddr $destination tcp dport $tcp_exit ct status dnat counter masquerade"
    tcp_forward="iifname \"$iface\" oifname \"$iface\" ip daddr $destination tcp dport $tcp_exit ct status dnat counter accept"
fi
cat > /etc/blackice-relay.nft <<EOF
table ip blackice_relay {
 chain prerouting {
  type nat hook prerouting priority dstnat; policy accept;
  $udp_pre
  $tcp_pre
 }
 chain postrouting {
  type nat hook postrouting priority srcnat; policy accept;
  $udp_post
  $tcp_post
 }
 chain forward {
  type filter hook forward priority filter; policy drop;
  ct state invalid drop
  $udp_forward
  $tcp_forward
  ct state established,related counter accept
 }
}
EOF
cat > /etc/systemd/system/blackice-relay.service <<'EOF'
[Unit]
Description=VPN TCP/UDP entry relay
Wants=network-online.target
After=systemd-sysctl.service network-online.target nftables.service
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStartPre=/usr/sbin/nft -c -f /etc/blackice-relay.nft
ExecStart=/usr/sbin/nft -f /etc/blackice-relay.nft
ExecStop=-/usr/sbin/nft delete table ip blackice_relay
[Install]
WantedBy=multi-user.target
EOF
chmod 600 /etc/blackice-relay.nft
nft -c -f /etc/blackice-relay.nft
printf 'net.ipv4.ip_forward = 1\n' > /etc/sysctl.d/90-blackice-relay.conf
sysctl -w net.ipv4.ip_forward=1
systemctl daemon-reload
systemctl enable --now blackice-relay.service
echo 'Installed. Automatic rollback in 5 minutes. Keep the old direct VPN connected.'
echo 'Test a separate device, then: bash /var/lib/awg-relay-kit/confirm-entry.sh'
echo 'Manual rollback: bash /var/lib/awg-relay-kit/rollback-entry.sh'
