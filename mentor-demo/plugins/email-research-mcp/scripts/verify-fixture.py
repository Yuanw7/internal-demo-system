#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from research_hub.models import SearchRequest
from research_hub.service import RetrievalHub


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()

    hub = RetrievalHub(args.data_dir)
    search = hub.search(SearchRequest(query="Aurora Compute", limit=10))
    with hub.database.connection() as connection:
        run = connection.execute(
            "SELECT status,item_count,error_count,folder_counts_json "
            "FROM email_sync_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        attribution_rows = connection.execute(
            "SELECT resolution_status,count(*) count FROM document_source_attributions "
            "GROUP BY resolution_status"
        ).fetchall()
    attributions = {row["resolution_status"]: row["count"] for row in attribution_rows}

    if run is None or run["status"] != "complete" or run["item_count"] != 5:
        raise RuntimeError("fixture_sync_incomplete")
    if run["error_count"] != 0:
        raise RuntimeError("fixture_sync_has_errors")
    if attributions != {"matched": 4, "unmatched": 1}:
        raise RuntimeError("fixture_attribution_mismatch")
    if hub.stats()["documents"] != 5 or search["total"] != 4:
        raise RuntimeError("fixture_deduplication_mismatch")

    print(
        json.dumps(
            {
                "status": "pass",
                "documents": 5,
                "deduplicated_search_results": 4,
                "policy_version": search["policy_version"],
                "attributions": attributions,
                "result_sources": [item["source_id"] for item in search["results"]],
                "real_content_processed": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
