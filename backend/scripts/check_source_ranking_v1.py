#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from research_hub.cli import seed_source_ranking_v1_demo
from research_hub.mcp_server import create_mcp
from research_hub.models import PolicyUpdate, RetrievalPolicy
from research_hub.service import RetrievalHub


async def check() -> dict:
    with TemporaryDirectory(prefix="source-ranking-v1-") as directory:
        hub = RetrievalHub(Path(directory))
        seeded = seed_source_ranking_v1_demo(hub)
        server = create_mcp(hub)
        _, before = await server.call_tool(
            "search_documents", {"request": {"query": "芯片需求", "limit": 5}}
        )
        current = hub.policy()
        policy = RetrievalPolicy.model_validate(current["policy"])
        inverted = policy.model_copy(
            update={
                "source_weights": policy.source_weights
                | {"fixture_orion_lee": 0.8, "fixture_northstar_research": 1.35}
            }
        )
        updated = hub.update_policy(
            PolicyUpdate(expected_version=current["version"], policy=inverted)
        )
        _, after = await server.call_tool(
            "search_documents", {"request": {"query": "芯片需求", "limit": 5}}
        )
        rerun = seed_source_ranking_v1_demo(hub)

        if seeded["sync"]["status"] != "complete":
            raise RuntimeError("email_sync_not_complete")
        if before["results"][0]["source_id"] != "fixture_orion_lee":
            raise RuntimeError("default_priority_not_applied")
        if after["results"][0]["source_id"] != "fixture_northstar_research":
            raise RuntimeError("updated_priority_not_applied")
        if after["policy_version"] != updated["version"]:
            raise RuntimeError("mcp_policy_snapshot_mismatch")
        if rerun["ingest"]["unchanged"] != 2:
            raise RuntimeError("v1_rerun_not_idempotent")

        return {
            "version": seeded["version"],
            "schema_migration": 3,
            "information_sources": len(seeded["information_sources"]),
            "sync_status": seeded["sync"]["status"],
            "folder_counts": seeded["sync"]["folder_counts"],
            "attributions": [item["status"] for item in seeded["attributions"]],
            "before_policy_version": before["policy_version"],
            "before_first": before["results"][0]["source_id"],
            "after_policy_version": after["policy_version"],
            "after_first": after["results"][0]["source_id"],
            "rerun_unchanged": rerun["ingest"]["unchanged"],
            "mcp_contract_changed": False,
            "real_content_processed": False,
        }


def main() -> int:
    print(json.dumps(asyncio.run(check()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
