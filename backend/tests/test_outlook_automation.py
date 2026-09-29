from __future__ import annotations

from io import BytesIO

from pypdf import PdfWriter

from research_hub.outlook_automation import (
    FixtureOutlookDeltaClient,
    OutlookAttachment,
    OutlookAutomation,
    OutlookDeltaPage,
    OutlookMessage,
)
from research_hub.service import RetrievalHub
from research_hub.source_ranking import (
    DEFAULT_SOURCE_RANKING_V1_PATH,
    load_source_ranking_catalog,
)


class FakeSemantic:
    def __init__(self):
        self.builds = 0

    def build(self, database, *, batch_size=64):
        self.builds += 1
        with database.connection() as connection:
            chunks = connection.execute("SELECT count(*) FROM chunks").fetchone()[0]
        return {"corpus_digest": f"outlook-generation-{self.builds}", "chunk_count": chunks}

    def is_current(self, _connection):
        return True

    def search(self, _query, limit=300):
        return []


class FakeOCR:
    def extract_text(self, name, content):
        assert name.endswith(".pdf")
        assert content
        return "Fictional OCR GPU demand evidence."


def blank_pdf() -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(output)
    return output.getvalue()


def message(message_id: str, attachments=()):
    return OutlookMessage(
        id=message_id,
        change_key=f"change-{message_id}",
        internet_message_id=f"<{message_id}@fictional.example>",
        folder_id="inbox_sellside",
        subject=f"Fictional GPU update {message_id}",
        body_text="Fictional NVIDIA GPU demand and AI infrastructure evidence.",
        received_at="2026-09-29T08:00:00+08:00",
        sender_name="Fictional Orion Lee",
        sender_address="orion.lee@fictional.example",
        attachments=tuple(attachments),
    )


def test_outlook_delta_pages_publish_parent_and_attachment(tmp_path):
    semantic = FakeSemantic()
    hub = RetrievalHub(tmp_path / "hub", semantic_index=semantic)
    client = FixtureOutlookDeltaClient(
        [
            OutlookDeltaPage(
                (
                    message(
                        "mail-1",
                        [
                            OutlookAttachment(
                                "attachment-1",
                                "fictional-gpu-note.txt",
                                "text/plain",
                                b"Fictional GPU supply evidence.",
                            )
                        ],
                    ),
                )
            ),
            OutlookDeltaPage((), delta_cursor="fixture-delta:2"),
        ]
    )
    worker = OutlookAutomation(
        hub,
        client,
        catalog=load_source_ranking_catalog(DEFAULT_SOURCE_RANKING_V1_PATH),
    )

    result = worker.run_once()
    assert result["pages"] == 2
    assert result["checkpoint"] == "fixture-delta:2"
    assert result["summary"]["counts"]["processed"] == 2
    assert semantic.builds == 1
    items = hub.ingestion_items(limit=10)["items"]
    parent = next(hub.ingestion_item(item["id"]) for item in items if item["display_name"].startswith("Fictional"))
    child = next(hub.ingestion_item(item["id"]) for item in items if item["display_name"].endswith(".txt"))
    with hub.database.connection() as connection:
        parent_provenance = connection.execute(
            "SELECT item_kind FROM ingestion_items WHERE id=?", (parent["id"],)
        ).fetchone()
        child_provenance = connection.execute(
            "SELECT item_kind,parent_item_id,required_for_parent FROM ingestion_items WHERE id=?",
            (child["id"],),
        ).fetchone()
    assert parent_provenance["item_kind"] == "email"
    assert child_provenance["item_kind"] == "attachment"
    assert child_provenance["parent_item_id"] == parent["id"]
    assert bool(child_provenance["required_for_parent"]) is True
    assert parent["semantic_generation_id"] == child["semantic_generation_id"]
    with hub.database.connection() as connection:
        source_ids = {
            row[0] for row in connection.execute("SELECT DISTINCT source_id FROM documents")
        }
    assert source_ids == {"fixture_orion_lee"}


def test_required_scanned_pdf_blocks_entire_email_without_ocr(tmp_path):
    semantic = FakeSemantic()
    hub = RetrievalHub(tmp_path / "hub", semantic_index=semantic)
    client = FixtureOutlookDeltaClient(
        [
            OutlookDeltaPage(
                (
                    message(
                        "mail-scan",
                        [
                            OutlookAttachment(
                                "scan-1",
                                "fictional-scan.pdf",
                                "application/pdf",
                                blank_pdf(),
                            )
                        ],
                    ),
                ),
                delta_cursor="fixture-delta:scan",
            )
        ]
    )
    worker = OutlookAutomation(hub, client)

    result = worker.run_once()
    assert result["summary"]["counts"]["failed"] == 2
    assert result["summary"]["counts"]["processed"] == 0
    assert semantic.builds == 0
    failed = [hub.ingestion_item(item["id"]) for item in hub.ingestion_items(status="failed")["items"]]
    assert {item["error_code"] for item in failed} == {
        "pdf_has_no_extractable_text_ocr_required",
        "required_attachment_failed",
    }
    assert hub.stats()["documents"] == 0


def test_outlook_resume_uses_persisted_delta_cursor(tmp_path):
    hub = RetrievalHub(tmp_path / "hub", semantic_index=FakeSemantic())
    first_client = FixtureOutlookDeltaClient(
        [OutlookDeltaPage((), delta_cursor="fixture-delta:1")]
    )
    OutlookAutomation(hub, first_client).run_once()

    second_client = FixtureOutlookDeltaClient(
        [OutlookDeltaPage((), delta_cursor="fixture-delta:unused")]
    )
    result = OutlookAutomation(hub, second_client).run_once()
    assert second_client.calls == ["fixture-delta:1"]
    assert result["checkpoint"] == "fixture-delta:1"


def test_scanned_pdf_can_publish_through_configured_ocr_adapter(tmp_path):
    semantic = FakeSemantic()
    hub = RetrievalHub(tmp_path / "hub", semantic_index=semantic)
    client = FixtureOutlookDeltaClient(
        [
            OutlookDeltaPage(
                (
                    message(
                        "mail-ocr",
                        [
                            OutlookAttachment(
                                "scan-ocr",
                                "fictional-ocr.pdf",
                                "application/pdf",
                                blank_pdf(),
                            )
                        ],
                    ),
                ),
                delta_cursor="fixture-delta:ocr",
            )
        ]
    )
    result = OutlookAutomation(hub, client, ocr=FakeOCR()).run_once()
    assert result["summary"]["counts"]["processed"] == 2
    assert semantic.builds == 1
    with hub.database.connection() as connection:
        metadata = connection.execute(
            "SELECT metadata_json FROM document_versions WHERE title='fictional-ocr.pdf'"
        ).fetchone()[0]
    assert '"extraction_method":"ocr"' in metadata


def test_unknown_outlook_sender_uses_fallback_and_records_unmatched_attribution(tmp_path):
    hub = RetrievalHub(tmp_path / "hub", semantic_index=FakeSemantic())
    unknown = OutlookMessage(
        id="mail-unknown",
        change_key="change-unknown",
        internet_message_id="<unknown@fictional.example>",
        folder_id="inbox",
        subject="Fictional unknown source",
        body_text="Fictional GPU market observation.",
        received_at="2026-09-29T08:00:00+08:00",
        sender_name="Unknown Fictional Sender",
        sender_address="unknown@fictional.example",
    )
    client = FixtureOutlookDeltaClient(
        [OutlookDeltaPage((unknown,), delta_cursor="fixture-delta:unknown")]
    )
    OutlookAutomation(
        hub,
        client,
        catalog=load_source_ranking_catalog(DEFAULT_SOURCE_RANKING_V1_PATH),
    ).run_once()
    with hub.database.connection() as connection:
        source_id = connection.execute("SELECT source_id FROM documents").fetchone()[0]
        attribution = connection.execute(
            "SELECT resolution_status FROM document_source_attributions"
        ).fetchone()[0]
    assert source_id == "outlook_unmatched"
    assert attribution == "unmatched"
