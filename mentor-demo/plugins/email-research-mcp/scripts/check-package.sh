#!/usr/bin/env bash
set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHECK_ROOT="$(mktemp -d -t email-research-mcp-check.XXXXXX)"
trap 'rm -rf "$CHECK_ROOT"' EXIT

python3 -m venv "$CHECK_ROOT/venv"
"$CHECK_ROOT/venv/bin/python" -m pip install -q -e "$PLUGIN_ROOT/runtime"
"$CHECK_ROOT/venv/bin/python" "$PLUGIN_ROOT/scripts/import-email-export.py" \
  --input-dir "$PLUGIN_ROOT/assets/fixture-mail" \
  --data-dir "$CHECK_ROOT/data" \
  --source-config "$PLUGIN_ROOT/assets/source-rankings.example.json" \
  --window-start "2026-09-28T00:00:00+08:00" \
  --window-end "2026-09-29T00:00:00+08:00"
"$CHECK_ROOT/venv/bin/python" "$PLUGIN_ROOT/scripts/verify-fixture.py" \
  --data-dir "$CHECK_ROOT/data"
EMAIL_RESEARCH_HOME="$CHECK_ROOT" \
  "$CHECK_ROOT/venv/bin/python" "$PLUGIN_ROOT/scripts/verify-mcp.py" \
  --plugin-root "$PLUGIN_ROOT"
