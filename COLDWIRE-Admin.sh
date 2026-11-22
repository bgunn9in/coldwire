#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ $# == 0 && ! -f private/coldwire-installation/operator.json ]]; then
    data_home=${XDG_DATA_HOME:-${HOME:+$HOME/.local/share}}
    if [[ $data_home == /* && -f "$data_home/coldwire/access-panel/operator.json" ]]; then
        set -- --folder "$data_home/coldwire/access-panel"
    fi
fi
exec bash ./setup.sh "$@"
