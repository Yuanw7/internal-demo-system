from __future__ import annotations

import json
import os
import secrets
import sys
from pathlib import Path


def credentials(path: Path) -> tuple[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        if path.stat().st_size > 4096:
            raise ValueError("credentials_file_too_large")
        values = json.loads(path.read_text(encoding="utf-8-sig"))
    read = os.environ.get("RESEARCH_HUB_READ_TOKEN", values.get("read_token", ""))
    admin = os.environ.get("RESEARCH_HUB_ADMIN_TOKEN", values.get("admin_token", ""))
    if len(read) < 32 or len(admin) < 32 or read == admin:
        raise ValueError("credentials_required_run_init")
    return read, admin


def initialize(data_dir: Path, credentials_path: Path, project_dir: Path) -> dict:
    data_dir.mkdir(parents=True, exist_ok=True)
    credentials_path.parent.mkdir(parents=True, exist_ok=True)
    created = False
    try:
        descriptor = os.open(credentials_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        credentials(credentials_path)
    else:
        values = {
            "read_token": secrets.token_urlsafe(32),
            "admin_token": secrets.token_urlsafe(32),
        }
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(values, indent=2) + "\n")
        created = True

    python = str(Path(sys.executable).resolve())
    data = str(data_dir.resolve())
    cwd = str(project_dir.resolve())
    snippet = (
        "[mcp_servers.internalResearch]\n"
        f'command = "{python}"\n'
        f'args = ["-m", "research_hub.cli", "--data-dir", "{data}", "stdio"]\n'
        f'cwd = "{cwd}"\n'
    )
    config_path = data_dir / "codex-mcp.local.toml"
    if not config_path.exists():
        config_path.write_text(snippet, encoding="utf-8")
    return {
        "credentials_created": created,
        "credentials_file": str(credentials_path.resolve()),
        "codex_config_snippet": str(config_path.resolve()),
    }
