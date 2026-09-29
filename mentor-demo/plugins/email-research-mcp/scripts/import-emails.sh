#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 <window-start-iso8601> <window-end-iso8601>" >&2
  exit 2
fi

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_ROOT="${EMAIL_RESEARCH_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/email-research-mcp}"
PYTHON_PATH="$STATE_ROOT/venv/bin/python"

if [[ ! -x "$PYTHON_PATH" ]]; then
  echo "Run scripts/setup.sh first." >&2
  exit 1
fi

exec "$PYTHON_PATH" "$PLUGIN_ROOT/scripts/import-email-export.py" \
  --input-dir "$STATE_ROOT/inbox-export" \
  --data-dir "$STATE_ROOT/data" \
  --source-config "$STATE_ROOT/source-rankings.json" \
  --window-start "$1" \
  --window-end "$2"
