#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 && -f /var/lib/awg-relay-kit/old-ip-forward ]] || { echo 'No kit-managed entry installation'; exit 1; }
previous=$(cat /var/lib/awg-relay-kit/old-ip-forward)
[[ $previous == 0 || $previous == 1 ]] || exit 1
systemctl stop blackice-relay-safety.timer || true
systemctl disable --now blackice-relay.service || true
if nft list table ip blackice_relay >/dev/null 2>&1; then nft delete table ip blackice_relay; fi
rm -f /etc/blackice-relay.nft /etc/systemd/system/blackice-relay.service /etc/sysctl.d/90-blackice-relay.conf
sysctl -w "net.ipv4.ip_forward=$previous"
systemctl daemon-reload
echo 'Relay removed; previous forwarding value restored. State retained in /var/lib/awg-relay-kit.'
