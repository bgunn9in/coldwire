#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
python3 -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ required"'
[[ -x .venv/bin/python ]] || python3 -m venv .venv
.venv/bin/python -m pip install --disable-pip-version-check -r requirements-deploy.txt
exec .venv/bin/python deploy.py "$@"
