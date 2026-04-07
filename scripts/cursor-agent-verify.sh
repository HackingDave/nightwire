#!/usr/bin/env bash
# Deterministic checks after agent code changes. Used by Cursor stop hook and manually before deploy.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
echo "== cursor-agent-verify: nightwire (pytest) =="
if [[ -f "$ROOT/.venv/bin/activate" ]]; then
  # shellcheck source=/dev/null
  source "$ROOT/.venv/bin/activate"
elif [[ -f "$ROOT/venv/bin/activate" ]]; then
  # shellcheck source=/dev/null
  source "$ROOT/venv/bin/activate"
fi
python3 -m pytest
echo "== cursor-agent-verify: OK =="
