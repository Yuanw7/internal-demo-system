#!/usr/bin/env python3
from __future__ import annotations

import json
from tempfile import TemporaryDirectory
from pathlib import Path

from research_hub.models import (
    DocumentInput,
    IngestRequest,
    PolicyUpdate,
    RetrievalPolicy,
    SearchRequest,
    SourceDefinition,
)
from research_hub.service import RetrievalHub
from research_hub.source_ranking import SourceCandidate, load_source_ranking_catalog


def main() -> int:
    catalog = load_source_ranking_catalog()
    primary = catalog.resolve_primary(
        [
            SourceCandidate("research_platform", "Market Library"),
            SourceCandidate("analyst", "O. Lee"),
        ]
    )
    if not primary.source:
        raise RuntimeError("fixture_primary_source_not_resolved")

    with TemporaryDirectory(prefix="source-ranking-v0-") as directory:
        hub = RetrievalHub(Path(directory))
        source_ids = ("fixture_orion_lee", "fixture_public_news")
        for source_id in source_ids:
            source = catalog.sources[source_id]
            hub.upsert_source(SourceDefinition(id=source.id, name=source.display_name, kind="demo"))
            hub.ingest(
                IngestRequest(
                    source_id=source_id,
                    documents=[
                        DocumentInput(
                            external_id="evidence",
                            title=f"{source.display_name}：虚构芯片需求",
                            body="【虚构测试数据】芯片需求增长，资本开支仍存在不确定性。",
                        )
                    ],
                )
            )

        preferred = hub.update_policy(
            PolicyUpdate(
                expected_version=1,
                policy=RetrievalPolicy(
                    source_weights=catalog.policy_weights(source_ids), recency_boost=0
                ),
            )
        )
        preferred_search = hub.search(SearchRequest(query="芯片需求"))
        inverted = hub.update_policy(
            PolicyUpdate(
                expected_version=preferred["version"],
                policy=RetrievalPolicy(
                    source_weights={
                        "fixture_orion_lee": 0.8,
                        "fixture_public_news": 1.35,
                    },
                    recency_boost=0,
                ),
            )
        )
        inverted_search = hub.search(SearchRequest(query="芯片需求"))

    evidence = {
        "catalog_version": catalog.version,
        "resolved_primary_source": primary.source.id,
        "preferred_policy_version": preferred_search["policy_version"],
        "preferred_first": preferred_search["results"][0]["source_id"],
        "inverted_policy_version": inverted_search["policy_version"],
        "inverted_first": inverted_search["results"][0]["source_id"],
        "mcp_contract_changed": False,
        "real_content_processed": False,
    }
    if evidence["preferred_first"] != "fixture_orion_lee":
        raise RuntimeError("priority_1_source_not_preferred")
    if evidence["inverted_first"] != "fixture_public_news":
        raise RuntimeError("updated_policy_not_applied")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
