#!/usr/bin/env bash
# Fresh automatic installation; restoration lives in restore-exit.sh.
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec python3 "$script_dir/../install_exit.py" install "$@"
