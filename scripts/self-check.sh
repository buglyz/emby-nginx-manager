#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

python3 -m py_compile webui.py
python3 -m unittest discover -s tests
sh -n install.sh bin/emby
bash -n deploy.sh
sh tests/dry-run.sh
sh tests/install-archive.sh
sh tests/wrapper.sh
