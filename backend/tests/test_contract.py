from __future__ import annotations

import json
from pathlib import Path

from research_hub.api import create_app
from research_hub.service import RetrievalHub


def test_backend_covers_the_archived_api_contract(tmp_path):
    root = Path(__file__).resolve().parents[2]
    contract = json.loads((root / "docs/contracts/openapi.json").read_text(encoding="utf-8"))
    app = create_app(RetrievalHub(tmp_path / "hub"), "r" * 40, "a" * 40)
    actual = app.openapi()
    assert actual["info"]["version"] == contract["info"]["version"] == "1.1.0"
    assert set(actual["paths"]) == set(contract["paths"])
    for path, operations in contract["paths"].items():
        assert set(operations) <= set(actual["paths"][path])
    assert set(contract["components"]["schemas"]) <= set(actual["components"]["schemas"])
