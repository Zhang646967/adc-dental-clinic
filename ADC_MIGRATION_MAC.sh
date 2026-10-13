#!/bin/bash
# Migration CLI needs host Python 3.11+, but never imports host Django/PostgreSQL.
set -euo pipefail
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
if ! command -v python3 >/dev/null; then
  echo 'Migration tools require host Python 3.11+. VERIFY_ISOLATED_MAC.sh requires Docker only.'
  exit 2
fi
exec python3 "$ROOT/scripts/migration_tool.py" "$@"
