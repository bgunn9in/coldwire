#!/usr/bin/env bash
# Shell-only checks work even before Python/iproute2 have been bootstrapped.
set -euo pipefail
export LC_ALL=C
[[ $EUID == 0 ]] || { echo 'Root/sudo required'; exit 1; }
source /etc/os-release
case "${ID:-}:${VERSION_ID:-}" in
    ubuntu:22.04|ubuntu:24.04|ubuntu:26.04|debian:12|debian:13) ;;
    *) echo 'Ubuntu 22.04/24.04/26.04 LTS or Debian 12/13 required'; exit 1 ;;
esac
[[ $(uname -m) == x86_64 && -d /run/systemd/system ]] || { echo 'amd64 with systemd required'; exit 1; }
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
echo 'Clean server host check passed'
