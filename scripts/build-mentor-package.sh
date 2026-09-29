#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR="$REPO_ROOT/artifacts/mentor"
OUTPUT_PATH="$OUTPUT_DIR/email-research-mcp-mentor-demo-v1.zip"
PLUGIN_ROOT="$REPO_ROOT/mentor-demo/plugins/email-research-mcp"
RUNTIME_ROOT="$PLUGIN_ROOT/runtime"

mkdir -p "$OUTPUT_DIR"
rm -rf "$RUNTIME_ROOT"
mkdir -p "$RUNTIME_ROOT/src/research_hub/config"
cp "$REPO_ROOT/backend/pyproject.toml" "$RUNTIME_ROOT/pyproject.toml"
cp "$REPO_ROOT"/backend/src/research_hub/*.py "$RUNTIME_ROOT/src/research_hub/"
cp "$REPO_ROOT"/backend/src/research_hub/config/*.json "$RUNTIME_ROOT/src/research_hub/config/"
rm -f "$OUTPUT_PATH"
cd "$REPO_ROOT"
zip -q -r -X "$OUTPUT_PATH" mentor-demo \
  -x '*/__pycache__/*' '*.pyc' '*/.DS_Store' '*/data/*' '*/venv/*'

echo "$OUTPUT_PATH"
