#!/usr/bin/env bash
# Marks the workspace so the stop hook knows the agent edited files this generation.
set -euo pipefail
DATA="$(cat)"
ROOT="$(echo "$DATA" | python3 -c 'import json,sys; d=json.load(sys.stdin); r=d.get("workspace_roots") or []; print(r[0] if r else "")')"
if [[ -z "$ROOT" ]]; then
  exit 0
fi
mkdir -p "$ROOT/.cursor"
touch "$ROOT/.cursor/.agent-edited-flag"
exit 0
