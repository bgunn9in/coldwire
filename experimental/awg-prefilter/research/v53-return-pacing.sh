#!/bin/sh
set -eu
[ "$(hostname)" = kit-entry ]
dev=enp0s3
rate=${1-260}
case "$rate" in
    260|360) ;;
    *) printf '%s\n' 'Expected a lab rate of 260 or 360 Mbit/s.' >&2; exit 2 ;;
esac

# The fourth band is reserved for return UDP. Keep the A-to-B netem band.
tc qdisc replace dev "$dev" root handle 1: prio bands 4
tc qdisc replace dev "$dev" parent 1:3 handle 30: netem delay 150ms 30ms distribution normal limit 100000
tc qdisc replace dev "$dev" parent 1:4 handle 40: tbf rate "${rate}mbit" burst 32768 limit 8388608
tc filter replace dev "$dev" protocol ip parent 1: prio 1 u32 match ip dst 192.168.76.20/32 flowid 1:3
tc filter replace dev "$dev" protocol ip parent 1: prio 2 flower ip_proto udp src_ip 192.168.76.10 src_port 32497 classid 1:4
