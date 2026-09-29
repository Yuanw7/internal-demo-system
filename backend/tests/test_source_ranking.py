from __future__ import annotations

import pytest

from research_hub.models import (
    DocumentInput,
    IngestRequest,
    PolicyUpdate,
    RetrievalPolicy,
    SearchRequest,
    SourceDefinition,
)
from research_hub.cli import seed_source_ranking_demo, seed_source_ranking_v1_demo
from research_hub.service import HubError, RetrievalHub
from research_hub.source_ranking import (
    SourceCandidate,
    SourceRankingCatalog,
    load_source_ranking_catalog,
)


def test_v0_catalog_resolves_alias_and_primary_role():
    catalog = load_source_ranking_catalog()
    alias = catalog.resolve("  O. LEE ")
    assert alias.status == "matched"
    assert alias.source_ids == ("fixture_orion_lee",)
    assert alias.matched_by == "alias"

    primary = catalog.resolve_primary(
        [
            SourceCandidate("research_platform", "Market Library"),
            SourceCandidate("institution", "Northstar Research"),
            SourceCandidate("analyst", "orion.lee@fictional.example"),
        ]
    )
    assert primary.status == "matched"
    assert primary.source and primary.source.id == "fixture_orion_lee"
    assert primary.role == "analyst"


def test_v0_catalog_reports_ambiguous_and_unmatched():
    config = {
        "version": "test-v0",
        "tier_weights": {"1": 1.35, "2": 1.15, "3": 1.0, "4": 0.8},
        "role_precedence": ["analyst", "institution"],
        "sources": [
            {
                "id": "one",
                "display_name": "Fictional One",
                "source_type": "analyst",
                "priority_tier": 1,
                "aliases": ["Shared Alias"],
            },
            {
                "id": "two",
                "display_name": "Fictional Two",
                "source_type": "analyst",
                "priority_tier": 2,
                "aliases": ["Shared Alias"],
            },
        ],
    }
    catalog = SourceRankingCatalog(config)
    assert catalog.resolve("Shared Alias").status == "ambiguous"
    assert catalog.resolve("Unknown Person").status == "unmatched"


def test_v0_demo_seed_is_idempotent(tmp_path):
    hub = RetrievalHub(tmp_path / "seeded")
    first = seed_source_ranking_demo(hub)
    second = seed_source_ranking_demo(hub)
    assert first["ingest"]["created"] == 2
    assert second["ingest"]["unchanged"] == 2
    assert first["policy_version"] == second["policy_version"] == 2
    assert second["stats"]["documents"] == 2
    assert second["real_content_processed"] is False


def test_v1_email_batch_and_attribution_are_persistent_and_idempotent(tmp_path):
    hub = RetrievalHub(tmp_path / "v1")
    first = seed_source_ranking_v1_demo(hub)
    second = seed_source_ranking_v1_demo(hub)
    assert first["sync"]["status"] == "complete"
    assert first["sync"]["folder_counts"] == {
        "inbox": 1,
        "inbox_sellside": 1,
        "inbox_third_party": 0,
    }
    assert {item["information_source_id"] for item in first["attributions"]} == {
        "fixture_orion_lee",
        "fixture_northstar_research",
    }
    assert second["ingest"]["unchanged"] == 2
    assert second["policy_version"] == first["policy_version"] == 2
    assert second["stats"]["documents"] == 2
    assert second["real_content_processed"] is False


def test_v1_email_batch_rejects_incomplete_folder_coverage(tmp_path):
    hub = RetrievalHub(tmp_path / "incomplete")
    hub.start_email_sync_run(
        "fixture-run",
        "fixture-account",
        "2026-09-28T00:00:00+08:00",
        "2026-09-29T00:00:00+08:00",
        ["inbox", "sellside", "third_party"],
    )
    with pytest.raises(HubError, match="email_sync_folder_coverage_incomplete"):
        hub.complete_email_sync_run("fixture-run", {"inbox": 0, "sellside": 0})


def test_v1_existing_dashboard_contract_lists_ranked_sources(tmp_path):
    from fastapi.testclient import TestClient

    from research_hub.api import create_app

    hub = RetrievalHub(tmp_path / "dashboard")
    seeded = seed_source_ranking_v1_demo(hub)
    headers = {"Authorization": "Bearer " + "r" * 40}
    with TestClient(create_app(hub, "r" * 40, "a" * 40)) as client:
        sources = client.get("/api/sources", headers=headers)
        policy = client.get("/api/policy", headers=headers)
    assert sources.status_code == policy.status_code == 200
    assert len(sources.json()["sources"]) == len(seeded["information_sources"]) == 8
    assert policy.json()["version"] == seeded["policy_version"] == 2


def test_v0_priority_policy_reorders_only_relevant_candidates(tmp_path):
    catalog = load_source_ranking_catalog()
    hub = RetrievalHub(tmp_path / "hub")
    source_ids = ("fixture_orion_lee", "fixture_public_news")
    for source_id in source_ids:
        source = catalog.sources[source_id]
        hub.upsert_source(SourceDefinition(id=source.id, name=source.display_name, kind="demo"))
    hub.ingest(
        IngestRequest(
            source_id="fixture_orion_lee",
            documents=[
                DocumentInput(
                    external_id="relevant",
                    title="虚构分析师：芯片需求",
                    body="【虚构测试数据】芯片需求增长，资本开支仍需验证。",
                ),
                DocumentInput(
                    external_id="irrelevant",
                    title="虚构消费观察",
                    body="【虚构测试数据】线下门店客流保持稳定。",
                ),
            ],
        )
    )
    hub.ingest(
        IngestRequest(
            source_id="fixture_public_news",
            documents=[
                DocumentInput(
                    external_id="relevant",
                    title="虚构新闻：芯片需求",
                    body="【虚构测试数据】芯片需求增长，库存周期仍需验证。",
                )
            ],
        )
    )

    updated = hub.update_policy(
        PolicyUpdate(
            expected_version=1,
            policy=RetrievalPolicy(
                source_weights=catalog.policy_weights(source_ids), recency_boost=0
            ),
        )
    )
    result = hub.search(SearchRequest(query="芯片需求"))
    assert updated["version"] == result["policy_version"] == 2
    assert result["results"][0]["source_id"] == "fixture_orion_lee"
    assert {item["title"] for item in result["results"]} == {
        "虚构分析师：芯片需求",
        "虚构新闻：芯片需求",
    }

    inverted = hub.update_policy(
        PolicyUpdate(
            expected_version=2,
            policy=RetrievalPolicy(
                source_weights={
                    "fixture_orion_lee": 0.8,
                    "fixture_public_news": 1.35,
                },
                recency_boost=0,
            ),
        )
    )
    next_result = hub.search(SearchRequest(query="芯片需求"))
    assert inverted["version"] == next_result["policy_version"] == 3
    assert next_result["results"][0]["source_id"] == "fixture_public_news"


@pytest.mark.asyncio
async def test_v0_mcp_search_documents_uses_next_policy_snapshot(tmp_path):
    pytest.importorskip("mcp")
    from research_hub.mcp_server import create_mcp

    catalog = load_source_ranking_catalog()
    hub = RetrievalHub(tmp_path / "mcp-hub")
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
                        body=f"【虚构测试数据】芯片需求增长；来源 {source.id}。",
                    )
                ],
            )
        )

    server = create_mcp(hub)
    hub.update_policy(
        PolicyUpdate(
            expected_version=1,
            policy=RetrievalPolicy(
                source_weights=catalog.policy_weights(source_ids), recency_boost=0
            ),
        )
    )
    _, preferred = await server.call_tool(
        "search_documents", {"request": {"query": "芯片需求"}}
    )
    assert preferred["policy_version"] == 2
    assert preferred["results"][0]["source_id"] == "fixture_orion_lee"

    hub.update_policy(
        PolicyUpdate(
            expected_version=2,
            policy=RetrievalPolicy(
                source_weights={
                    "fixture_orion_lee": 0.8,
                    "fixture_public_news": 1.35,
                },
                recency_boost=0,
            ),
        )
    )
    _, inverted = await server.call_tool(
        "search_documents", {"request": {"query": "芯片需求"}}
    )
    assert inverted["policy_version"] == 3
    assert inverted["results"][0]["source_id"] == "fixture_public_news"
