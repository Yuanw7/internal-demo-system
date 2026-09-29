#!/usr/bin/env bash
set -euo pipefail

STATE_ROOT="${EMAIL_RESEARCH_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/email-research-mcp}"
PYTHON_PATH="$STATE_ROOT/venv/bin/python"

if [[ ! -x "$PYTHON_PATH" ]]; then
  echo "Email Research MCP is not initialized. Run the plugin scripts/setup.sh first." >&2
  exit 1
fi

exec "$PYTHON_PATH" -m research_hub.cli --data-dir "$STATE_ROOT/data" stdio
