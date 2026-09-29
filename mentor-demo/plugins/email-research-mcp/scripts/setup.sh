#!/usr/bin/env bash
set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_ROOT="${EMAIL_RESEARCH_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/email-research-mcp}"
VENV_PATH="$STATE_ROOT/venv"

mkdir -p "$STATE_ROOT/inbox-export/Inbox/Anatole Must Read Sellside"
mkdir -p "$STATE_ROOT/inbox-export/Inbox/Anatole 3 Party Tracking"
mkdir -p "$STATE_ROOT/data"

python3 -m venv "$VENV_PATH"
"$VENV_PATH/bin/python" -m pip install -e "$PLUGIN_ROOT/runtime"

if [[ ! -f "$STATE_ROOT/source-rankings.json" ]]; then
  cp "$PLUGIN_ROOT/assets/source-rankings.example.json" "$STATE_ROOT/source-rankings.json"
fi

echo "Setup complete: $STATE_ROOT"
echo "Next: edit source-rankings.json, export emails, then run scripts/import-emails.sh."
