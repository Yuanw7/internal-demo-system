from __future__ import annotations

from research_hub.automation import FolderAutomation
from research_hub.service import RetrievalHub


class FakeSemantic:
    def __init__(self):
        self.builds = 0

    def build(self, database, *, batch_size=64):
        self.builds += 1
        with database.connection() as connection:
            chunks = connection.execute("SELECT count(*) FROM chunks").fetchone()[0]
        return {"corpus_digest": f"fixture-generation-{self.builds}", "chunk_count": chunks}

    def is_current(self, _connection):
        return True

    def search(self, _query, limit=300):
        return []


def automation(tmp_path):
    inbox = tmp_path / "capital-iq"
    inbox.mkdir()
    semantic = FakeSemantic()
    hub = RetrievalHub(tmp_path / "hub", semantic_index=semantic)
    worker = FolderAutomation(
        hub,
        inbox,
        connector_id="capital_iq_folder",
        connector_name="Capital IQ Folder",
        source_id="capital_iq",
        source_name="Capital IQ",
        settle_seconds=0,
    )
    return inbox, semantic, hub, worker


def test_folder_automation_requires_vector_publish_before_processed(tmp_path):
    inbox, semantic, hub, worker = automation(tmp_path)
    (inbox / "fictional-note.txt").write_text(
        "Fictional NVIDIA GPU demand evidence.", encoding="utf-8"
    )

    first = worker.run_once()
    assert first["discovered"] == 1
    assert first["summary"]["counts"]["processed"] == 1
    assert first["semantic_generation_id"] == "fixture-generation-1"
    item = hub.ingestion_items()["items"][0]
    detail = hub.ingestion_item(item["id"])
    assert detail["pipeline_stage"] == "publish"
    assert detail["semantic_generation_id"] == "fixture-generation-1"
    assert detail["searchable_at"]
    assert detail["document_ids"]

    second = worker.run_once()
    assert second["discovered"] == 0
    assert semantic.builds == 1
    assert second["summary"]["counts"]["processed"] == 1


def test_failed_item_can_be_requeued_with_optimistic_lock(tmp_path):
    inbox, _semantic, hub, worker = automation(tmp_path)
    (inbox / "broken.pdf").write_bytes(b"not-a-pdf")

    worker.run_once()
    failed = hub.ingestion_items(status="failed")["items"][0]
    response = hub.retry_ingestion_item(
        failed["id"], failed["state_version"], "fixture parser repair", "restart"
    )
    assert response["status"] == "retrying"
    assert hub.ingestion_summary()["counts"]["retrying"] == 1


def test_folder_waits_for_stability_and_records_checkpoint(tmp_path):
    inbox = tmp_path / "stable-inbox"
    inbox.mkdir()
    semantic = FakeSemantic()
    hub = RetrievalHub(tmp_path / "stable-hub", semantic_index=semantic)
    worker = FolderAutomation(
        hub,
        inbox,
        connector_id="stable_folder",
        connector_name="Stable Folder",
        source_id="stable_source",
        source_name="Stable Source",
        settle_seconds=5,
    )
    (inbox / "fictional-note.txt").write_text("Fictional evidence.", encoding="utf-8")

    first = worker.run_once()
    assert first["unstable"] == 1
    assert first["discovered"] == 0
    assert first["checkpoint_version"] >= 2

    with hub.database.connection() as connection:
        connection.execute(
            "UPDATE ingestion_source_objects SET stable_since='2020-01-01T00:00:00+00:00'"
        )
    second = worker.run_once()
    assert second["discovered"] == 1
    assert second["summary"]["counts"]["processed"] == 1


def test_folder_backpressure_and_deletion_are_observed_without_document_delete(tmp_path):
    inbox = tmp_path / "bounded-inbox"
    inbox.mkdir()
    semantic = FakeSemantic()
    hub = RetrievalHub(tmp_path / "bounded-hub", semantic_index=semantic)
    worker = FolderAutomation(
        hub,
        inbox,
        connector_id="bounded_folder",
        connector_name="Bounded Folder",
        source_id="bounded_source",
        source_name="Bounded Source",
        settle_seconds=0,
        max_queue_depth=1,
    )
    first_path = inbox / "a.txt"
    second_path = inbox / "b.txt"
    first_path.write_text("Fictional A.", encoding="utf-8")
    second_path.write_text("Fictional B.", encoding="utf-8")

    first = worker.run_once()
    assert first["discovered"] == 1
    assert first["backpressured"] == 1
    second = worker.run_once()
    assert second["discovered"] == 1
    assert second["summary"]["counts"]["processed"] == 2

    first_path.unlink()
    deleted = worker.run_once()
    assert deleted["deleted_observed"] == 1
    assert hub.stats()["documents"] == 2
