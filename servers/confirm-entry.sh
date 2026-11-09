#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 && -f /var/lib/awg-relay-kit/old-ip-forward ]] || { echo 'No kit-managed entry installation'; exit 1; }
systemctl is-active --quiet blackice-relay.service
nft list table ip blackice_relay >/dev/null
systemctl stop blackice-relay-safety.timer
echo 'Automatic rollback cancelled. Relay service remains enabled.'
