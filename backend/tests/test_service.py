from __future__ import annotations

from datetime import UTC, datetime

import pytest

from research_hub.models import (
    DocumentInput,
    IngestRequest,
    PolicyUpdate,
    RetrievalPolicy,
    SearchRequest,
    SourceDefinition,
)
from research_hub.service import HubError, RetrievalHub
from research_hub.util import query_expression


@pytest.fixture
def hub(tmp_path):
    service = RetrievalHub(tmp_path / "hub")
    for source, date in (("research", "2026-09-01T00:00:00Z"), ("filings", "2026-08-01T00:00:00Z")):
        service.upsert_source(SourceDefinition(id=source, name=source))
        service.ingest(
            IngestRequest(
                source_id=source,
                documents=[
                    DocumentInput(
                        external_id="one",
                        title="虚构芯片研究",
                        body="芯片需求增长。资本开支仍有不确定性。",
                        published_at=date,
                        metadata={"company": "虚构公司", "report_type": source},
                    )
                ],
            )
        )
    return service


def test_migrations_are_repeatable_and_policy_changes_ranking(hub):
    first = hub.search(SearchRequest(query="芯片"))
    old_first = first["results"][0]["source_id"]
    preferred = "filings" if old_first == "research" else "research"
    updated = hub.update_policy(
        PolicyUpdate(
            expected_version=1,
            policy=RetrievalPolicy(source_weights={old_first: 0.1, preferred: 8}, recency_boost=0),
        )
    )
    restarted = RetrievalHub(hub.database.path.parent)
    result = restarted.search(SearchRequest(query="芯片"))
    assert updated["version"] == result["policy_version"] == 2
    assert result["results"][0]["source_id"] == preferred
    assert result["results"][0]["score_details"]["source_weight"] == 8
    with pytest.raises(HubError, match="policy_version_conflict"):
        hub.update_policy(PolicyUpdate(expected_version=1, policy=RetrievalPolicy()))


def test_document_updates_create_immutable_versions(hub):
    old = hub.search(SearchRequest(query="资本开支", source_ids=["research"]))["results"][0]
    result = hub.ingest(
        IngestRequest(
            source_id="research",
            documents=[
                DocumentInput(
                    external_id="one",
                    title="虚构芯片研究修订版",
                    body="芯片需求下调。资本开支计划延期。",
                    published_at="2026-09-02T00:00:00Z",
                    metadata={"company": "虚构公司", "report_type": "research"},
                )
            ],
        )
    )
    assert result["updated"] == 1 and result["document_ids"] == [old["id"]]
    assert hub.ingest(
        IngestRequest(
            source_id="research",
            documents=[
                DocumentInput(
                    external_id="one",
                    title="虚构芯片研究修订版",
                    body="芯片需求下调。资本开支计划延期。",
                    published_at="2026-09-02T00:00:00Z",
                    metadata={"company": "虚构公司", "report_type": "research"},
                )
            ],
        )
    )["unchanged"] == 1
    with hub.database.connection() as connection:
        versions = connection.execute(
            "SELECT count(*) FROM document_versions WHERE document_id=?", (old["id"],)
        ).fetchone()[0]
    assert versions == 2
    assert "需求下调" in hub.fetch(old["id"])["text"]
    assert hub.search(SearchRequest(query="增长", source_ids=["research"]))["total"] == 0


def test_filters_citations_and_disabled_sources(hub):
    filtered = hub.search(
        SearchRequest(query="芯片", metadata={"report_type": "filings"}, since="2026-01-01T00:00:00Z")
    )
    assert [item["source_id"] for item in filtered["results"]] == ["filings"]
    item = filtered["results"][0]
    document = hub.fetch(item["id"])
    assert item["snippet"] == document["text"][item["citation"]["start"] : item["citation"]["end"]]
    hub.upsert_source(SourceDefinition(id="filings", name="filings", enabled=False))
    assert hub.search(SearchRequest(query="芯片", source_ids=["filings"]))["total"] == 0
    with pytest.raises(HubError, match="document_not_found"):
        hub.fetch(item["id"])


def test_recency_is_reproducible(hub):
    result = hub.search(SearchRequest(query="芯片"), now=datetime(2026, 9, 10, tzinfo=UTC))
    assert result["results"][0]["score_details"]["freshness"] > 0


def test_unknown_source_and_literal_query(hub):
    with pytest.raises(HubError, match="unknown_source"):
        hub.update_policy(
            PolicyUpdate(expected_version=1, policy=RetrievalPolicy(source_weights={"missing": 2}))
        )


def test_body_hash_marks_exact_cross_source_duplicates(hub):
    body = "Same normalized research body."
    for source in ("duplicate_a", "duplicate_b"):
        hub.upsert_source(SourceDefinition(id=source, name=source))
        hub.ingest(
            IngestRequest(
                source_id=source,
                documents=[DocumentInput(external_id="report", title=source, body=body)],
            )
        )
    with hub.database.connection() as connection:
        rows = connection.execute(
            "SELECT body_sha,count(*) FROM document_versions "
            "WHERE body=? GROUP BY body_sha",
            (body,),
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["body_sha"]
    assert rows[0][1] == 2
    assert hub.search(SearchRequest(query='" OR * --'))["total"] == 0


def test_natural_chinese_compound_query_recalls_distributed_terms(hub):
    result = hub.search(SearchRequest(query="芯片需求"))
    assert result["total"] == 1


def test_investment_query_planner_expands_entities_and_products():
    from research_hub.query_planner import plan_query

    plan = plan_query("英伟达具体显卡")
    assert plan.matched_concepts == ("nvidia", "gpu_products")
    assert "nvidia" in plan.lexical_expression
    assert "gb300" in plan.lexical_expression
    assert "blackwell" in plan.semantic_text


def test_semantic_candidate_participates_in_hybrid_ranking(tmp_path):
    class FakeSemantic:
        def __init__(self):
            self.hits = []

        def is_current(self, _connection):
            return True

        def search(self, _query, limit=300):
            return self.hits[:limit]

    semantic = FakeSemantic()
    service = RetrievalHub(tmp_path / "hybrid", semantic_index=semantic)
    service.upsert_source(SourceDefinition(id="research", name="research"))
    service.ingest(
        IngestRequest(
            source_id="research",
            documents=[
                DocumentInput(external_id="lexical", title="NVIDIA GPU", body="NVIDIA H100 demand"),
                DocumentInput(
                    external_id="semantic",
                    title="数据中心建设",
                    body="机柜电力、液冷和高速互联决定算力集群交付。",
                ),
            ],
        )
    )
    with service.database.connection() as connection:
        semantic.hits = [
            (connection.execute("SELECT max(id) FROM chunks").fetchone()[0], 0.88)
        ]
    result = service.search(SearchRequest(query="AI infra bottleneck"))
    assert {item["title"] for item in result["results"]} == {"数据中心建设"}


def test_english_question_stopwords_do_not_overconstrain(hub):
    assert query_expression("What is chip demand?") == '"chip" AND "demand"'
