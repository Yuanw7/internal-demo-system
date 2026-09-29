from __future__ import annotations

import json
from zipfile import ZipFile

from research_hub.chunking import chunk_document
from research_hub.parsing import documents_from_path, filename_date, parse_bytes


def test_text_json_and_filename_date(tmp_path):
    (tmp_path / "note_2026-09-03.txt").write_text("第一段。\n\n第二段。", encoding="utf-8")
    (tmp_path / "records.json").write_text(
        json.dumps({"external_id": "ignored", "title": "JSON", "body": "芯片内容"}),
        encoding="utf-8",
    )
    documents, errors = documents_from_path(tmp_path)
    assert not errors and len(documents) == 2
    assert any(document.published_at == "2026-09-03T00:00:00+00:00" for document in documents)
    assert filename_date("report_21_Aug_2026.pdf.pdf") == "2026-08-21T00:00:00+00:00"
    assert filename_date("two_2026-09-03_2026-09-04.pdf") == ""


def test_zip_container_is_read_without_extracting(tmp_path):
    archive = tmp_path / "Capital IQ_sample.zip"
    with ZipFile(archive, "w") as bundle:
        bundle.writestr("folder/note_21_Aug_2026.txt", "AI infrastructure demand")
        bundle.writestr("folder/ignored.bin", b"not research")
    documents, errors = documents_from_path(archive)
    assert errors == []
    assert len(documents) == 1
    assert documents[0].published_at == "2026-08-21T00:00:00+00:00"
    assert documents[0].metadata["archive_name"] == archive.name
    assert documents[0].metadata["archive_entry"] == "folder/note_21_Aug_2026.txt"


def test_chunking_uses_sentence_boundaries_and_page_scope():
    body = "第一句。第二句。第三句。"
    chunks = chunk_document("doc", "version", body, [(1, 0, len(body))], max_chars=8, overlap_chars=4)
    assert len(chunks) >= 2
    assert all(chunk.page == 1 for chunk in chunks)
    assert all(chunk.text == body[chunk.start : chunk.end] for chunk in chunks)


def test_empty_pdf_like_inputs_are_bounded():
    try:
        parse_bytes("x.pdf", b"not a pdf")
    except ValueError as exc:
        assert str(exc) == "pdf_parse_failed"


def test_eml_preserves_sender_identity_for_source_resolution():
    parsed = parse_bytes(
        "fixture.eml",
        (
            "From: Orion Lee <orion.lee@fictional.example>\n"
            "Date: Mon, 28 Sep 2026 08:30:00 +0800\n"
            "Message-ID: <fixture-001@fictional.example>\n"
            "Subject: Fictional update\n"
            "Content-Type: text/plain; charset=utf-8\n\n"
            "Fictional evidence."
        ).encode("utf-8"),
    )[0]
    assert parsed.metadata == {
        "email_from_name": "Orion Lee",
        "email_from_address": "orion.lee@fictional.example",
        "email_message_id": "<fixture-001@fictional.example>",
    }
