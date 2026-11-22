#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 ]] || exit 1
umask 077
state=/etc/coldwire-lockdown
pending=$state/pending.nft
active=$state/active.nft
timer=coldwire-lockdown-rollback
ticket=$state/pending.timer
exec 9>/run/coldwire-lockdown.lock
flock -x 9

if ! command -v nft >/dev/null; then
    nft() { /opt/coldwire-lockdown/nft "$@"; }
fi

rules() {
    if nft list table inet coldwire_lockdown >/dev/null 2>&1; then
        echo 'delete table inet coldwire_lockdown'
    fi
    if [[ -f $1 ]]; then cat -- "$1"; fi
}

case "${1:-}" in
    stage)
        [[ $# == 2 && ! -e $pending && -f $2 ]]
        if [[ ! -f $active ]] && nft list table inet coldwire_lockdown >/dev/null 2>&1; then
            echo KIT_ERROR=UNMANAGED_LOCKDOWN >&2
            exit 1
        fi
        rules "$2" | nft -c -f -
        systemctl enable coldwire-lockdown.service
        timer="$timer-$(cat /proc/sys/kernel/random/uuid)"
        install -m 600 -- "$2" "$pending"
        printf '%s\n' "$timer" > "$ticket"
        if ! systemd-run --quiet --unit="$timer" --on-active="${CW_ROLLBACK_AFTER:-3min}" \
            --timer-property=AccuracySec=1s /bin/bash "$(realpath -- "$0")" rollback "$timer"; then
            rm -f -- "$pending" "$ticket"
            exit 1
        fi
        rules "$pending" | nft -f -
        touch "$state/ssh-ready"
        ;;
    confirm)
        [[ $# == 1 && -f $pending && -f $ticket ]]
        timer=$(cat "$ticket")
        systemctl is-active --quiet "$timer.timer"
        mv -T -- "$pending" "$active"
        rm -f -- "$ticket"
        systemctl --no-block stop "$timer.timer"
        ;;
    rollback|load)
        if [[ $# == 2 ]]; then
            [[ $1 == rollback && -f $ticket && $(cat "$ticket") == "$2" ]] || exit 0
        else
            [[ $# == 1 ]]
        fi
        if [[ -f $pending || $1 == load ]]; then
            rules "$active" | nft -f -
            rm -f -- "$pending"
            if [[ -f $ticket ]]; then
                timer=$(cat "$ticket")
                rm -f -- "$ticket"
                systemctl --no-block stop "$timer.timer" 2>/dev/null || true
            fi
            if [[ ! -f $active ]]; then
                rm -f -- "$state/ssh-ready"
                systemctl --no-block stop coldwire-lockdown-ssh.service
                if [[ -f $state/pilot-upgrade ]]; then
                    rm -f -- /etc/systemd/system/coldwire-spa-pilot.service.d/50-lockdown.conf "$state/pilot-upgrade"
                    systemctl daemon-reload
                    systemctl --no-block try-restart coldwire-spa-pilot.service
                fi
            fi
        fi
        ;;
    *) echo 'Usage: stage-lockdown.sh stage FILE | confirm | rollback | load' >&2; exit 2 ;;
esac
