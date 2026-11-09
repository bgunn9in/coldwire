#!/usr/bin/env bash
# Shell-only checks work even before Python/iproute2 have been bootstrapped.
set -euo pipefail
export LC_ALL=C
[[ $EUID == 0 ]] || { echo 'Root/sudo required'; exit 1; }
source /etc/os-release
[[ $ID == ubuntu && $VERSION_ID == 22.04 && $(uname -m) == x86_64 && -d /run/systemd/system ]] || { echo 'Only Ubuntu 22.04 amd64 with systemd is supported'; exit 1; }
for path in /opt/awg-relay-kit /opt/amnezia /etc/awg-relay-kit-exit /etc/awg-relay-kit-xray /var/lib/awg-relay-kit /usr/local/libexec/awg-relay-kit /usr/local/libexec/awg-relay-kit-xray /root/awg-relay-kit-clients /root/awg-relay-kit-xray-clients /etc/blackice-relay.nft /etc/systemd/system/blackice-relay.service; do
    [[ ! -e $path ]] || { echo 'Existing installation/output detected'; exit 1; }
done
[[ $(cat /proc/sys/net/ipv4/ip_forward) == 0 ]] || { echo 'Existing forwarding detected'; exit 1; }
! command -v docker >/dev/null || { echo 'Existing Docker detected'; exit 1; }
if command -v nft >/dev/null; then [[ -z $(nft list tables) ]] || { echo 'Existing nftables detected'; exit 1; }; fi
if command -v ufw >/dev/null && ufw status | grep -q '^Status: active'; then echo 'Active UFW detected'; exit 1; fi
if [[ ${1:---check} == --bootstrap ]]; then
    export DEBIAN_FRONTEND=noninteractive
    missing=()
    command -v python3 >/dev/null || missing+=(python3)
    if ! command -v ip >/dev/null || ! command -v ss >/dev/null; then missing+=(iproute2); fi
    [[ -f /etc/ssl/certs/ca-certificates.crt ]] || missing+=(ca-certificates)
    command -v openssl >/dev/null || missing+=(openssl)
    if (( ${#missing[@]} )); then
        apt-get update -o Acquire::Retries=3
        apt-get install -y --no-install-recommends "${missing[@]}"
    fi
fi
echo 'Clean Ubuntu host check passed'
