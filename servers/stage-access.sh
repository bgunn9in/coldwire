#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Run as root.' >&2; exit 1; }
[[ $# == 1 && $1 == load ]] || { echo 'Usage: stage-access.sh load' >&2; exit 2; }
state=/etc/coldwire-access/active.nft
[[ -s $state ]]
exec 9>/run/coldwire-access.lock
flock -x 9
{
    if nft list table inet coldwire_access >/dev/null 2>&1; then
        echo 'delete table inet coldwire_access'
    fi
    cat -- "$state"
} | nft -f -
nft list chain inet coldwire_access admission >/dev/null
