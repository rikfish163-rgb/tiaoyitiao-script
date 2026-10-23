#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
python3 -c 'import sys; assert sys.version_info >= (3, 11), "需要 Python 3.11 或更新版本"'
python3 -m venv .venv
.venv/bin/python -m pip install --index-url https://pypi.org/simple -r requirements.txt
.venv/bin/python jump.py doctor
