#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m compileall -q src tests
bash -n scripts/install-deps.sh scripts/uninstall.sh
python3 -m py_compile scripts/rollback-check.py src/takt_engine/privileged_writer.py
printf '\nTests, Python-Syntax und Shell-Syntax erfolgreich.\n'
