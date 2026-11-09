#!/usr/bin/env bash
set -euo pipefail
[[ $# == 1 ]] || { echo 'Usage: sudo bash servers/backup-exit.sh NEW_PRIVATE_DIRECTORY'; exit 1; }
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec python3 "$script_dir/../install_exit.py" backup --output "$1"
