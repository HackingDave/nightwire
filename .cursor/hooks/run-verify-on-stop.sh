#!/usr/bin/env bash
# Runs deterministic verification after an agent turn that modified files (status completed).
set -euo pipefail
DATA="$(cat)"
STATUS="$(echo "$DATA" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status",""))')"
if [[ "$STATUS" != "completed" ]]; then
  exit 0
fi
ROOT="$(echo "$DATA" | python3 -c 'import json,sys; d=json.load(sys.stdin); r=d.get("workspace_roots") or []; print(r[0] if r else "")')"
if [[ -z "$ROOT" ]]; then
  exit 0
fi
FLAG="$ROOT/.cursor/.agent-edited-flag"
if [[ ! -f "$FLAG" ]]; then
  exit 0
fi
rm -f "$FLAG"
cd "$ROOT" || exit 0
if [[ -f "scripts/cursor-agent-verify.sh" ]]; then
  exec bash "scripts/cursor-agent-verify.sh"
fi
exit 0
