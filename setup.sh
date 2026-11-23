#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ${1:-} == --spa ]]; then shift; fi
if [[ ${1:-} == update-lists ]]; then
    shift
    exec bash ./COLDWIRE-Lists.sh "$@"
fi
if ! python3 -c 'import sys,sysconfig; sys.exit(not (sys.version_info >= (3,10) and not sysconfig.get_config_var(sys.argv[1])))' Py_GIL_DISABLED; then
    echo 'Standard CPython 3.10 or newer is required on the operator computer.' >&2
    exit 1
fi
if [[ ! -x .venv/bin/python ]] || ! .venv/bin/python -m pip --version >/dev/null 2>&1; then
    if ! python3 -m venv .venv; then
        echo 'Creating the Python environment failed. On Ubuntu and Debian, install python3-venv.' >&2
        exit 1
    fi
fi
.venv/bin/python -m pip install --disable-pip-version-check -r requirements-deploy.txt
exec .venv/bin/python coldwire_access.py "$@"
