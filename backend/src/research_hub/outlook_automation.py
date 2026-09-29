from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .models import DocumentInput, IngestRequest, SourceDefinition
from .parsing import PARSER_VERSION, parse_bytes
from .service import RetrievalHub
from .source_ranking import (
    SourceRankingCatalog,
    source_candidates_from_metadata,
)
from .util import digest, stable_json


@dataclass(frozen=True)
class OutlookAttachment:
    id: str
    name: str
    content_type: str
    content: bytes
    required: bool = True


@dataclass(frozen=True)
class OutlookMessage:
    id: str
    change_key: str
    internet_message_id: str
    folder_id: str
    subject: str
    body_text: str
    received_at: str
    sender_name: str = ""
    sender_address: str = ""
    attachments: tuple[OutlookAttachment, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class OutlookDeltaPage:
    messages: tuple[OutlookMessage, ...]
    next_cursor: str = ""
    delta_cursor: str = ""


class OutlookDeltaClient(Protocol):
    def fetch_delta(self, cursor: str) -> OutlookDeltaPage: ...


class OCRAdapter(Protocol):
    def extract_text(self, name: str, content: bytes) -> str: ...


class FixtureOutlookDeltaClient:
    """Deterministic Graph-shaped adapter used only with fictional test messages."""

    def __init__(self, pages: list[OutlookDeltaPage]):
        if not pages:
            raise ValueError("fixture_outlook_pages_required")
        self.pages = pages
        self.calls: list[str] = []

    def fetch_delta(self, cursor: str) -> OutlookDeltaPage:
        self.calls.append(cursor)
        if cursor.startswith("fixture-page:"):
            index = int(cursor.split(":", 1)[1])
        elif cursor.startswith("fixture-delta:"):
            return OutlookDeltaPage((), delta_cursor=cursor)
        elif cursor:
            raise ValueError("fixture_outlook_cursor_invalid")
        else:
            index = 0
        if index >= len(self.pages):
            raise ValueError("fixture_outlook_page_missing")
        page = self.pages[index]
        if index < len(self.pages) - 1 and not page.next_cursor:
            return OutlookDeltaPage(
                page.messages,
                next_cursor=f"fixture-page:{index + 1}",
            )
        return page


class OutlookAutomation:
    """Outlook delta ingestion independent of any concrete Microsoft auth client."""

    PIPELINE_VERSION = f"outlook-automation-v1:{PARSER_VERSION}"

    def __init__(
        self,
        hub: RetrievalHub,
        client: OutlookDeltaClient,
        *,
        connector_id: str = "outlook_mailbox",
        connector_name: str = "Outlook Mailbox",
        fallback_source_id: str = "outlook_unmatched",
        fallback_source_name: str = "Outlook Unmatched",
        worker_id: str = "local-outlook-worker",
        catalog: SourceRankingCatalog | None = None,
        ocr: OCRAdapter | None = None,
        max_pages_per_scan: int = 100,
    ):
        if max_pages_per_scan < 1:
            raise ValueError("invalid_outlook_page_limit")
        self.hub = hub
        self.client = client
        self.connector_id = connector_id
        self.fallback_source_id = fallback_source_id
        self.worker_id = worker_id
        self.catalog = catalog
        self.ocr = ocr
        self.max_pages_per_scan = max_pages_per_scan
        self.hub.upsert_ingestion_connector(
            connector_id,
            connector_name,
            "outlook",
            config={"adapter": "external", "max_pages_per_scan": max_pages_per_scan},
            semantic_required=True,
        )
        self.hub.upsert_source(
            SourceDefinition(id=fallback_source_id, name=fallback_source_name, kind="api")
        )
        if catalog:
            self.hub.sync_information_source_catalog(catalog, retrieval_kind="api")

    @staticmethod
    def _metadata(message: OutlookMessage) -> dict[str, str]:
        metadata = {
            "ingestion_channel": "outlook_delta",
            "email_folder": message.folder_id,
            "email_message_id": message.internet_message_id,
            "outlook_message_id": message.id,
            "outlook_change_key": message.change_key,
        }
        if message.sender_name:
            metadata["email_from_name"] = message.sender_name
        if message.sender_address:
            metadata["email_from_address"] = message.sender_address.casefold()
        return metadata

    def _source(self, metadata: dict[str, str]):
        if not self.catalog:
            return self.fallback_source_id, None
        resolution = self.catalog.resolve_primary(source_candidates_from_metadata(metadata))
        if resolution.source:
            return resolution.source.id, resolution
        return self.fallback_source_id, resolution

    def _persist(self, source_id: str, documents: list[DocumentInput], resolution) -> list[str]:
        result = self.hub.ingest(
            IngestRequest(source_id=source_id, documents=documents),
            parser_version=PARSER_VERSION,
        )
        if resolution:
            for document_id in result["document_ids"]:
                self.hub.record_primary_source(document_id, resolution)
        return result["document_ids"]

    def _attachment_documents(
        self, message: OutlookMessage, attachment: OutlookAttachment
    ) -> list[DocumentInput]:
        try:
            parsed = parse_bytes(attachment.name, attachment.content)
        except ValueError as exc:
            if str(exc) != "pdf_has_no_extractable_text_ocr_required" or self.ocr is None:
                raise
            text = self.ocr.extract_text(attachment.name, attachment.content).strip()
            if not text:
                raise ValueError("ocr_returned_no_text")
            metadata = self._metadata(message) | {
                "attachment_id": attachment.id,
                "attachment_name": attachment.name,
                "attachment_content_type": attachment.content_type,
                "extraction_method": "ocr",
            }
            return [
                DocumentInput(
                    external_id=f"{message.id}/attachments/{attachment.id}#0",
                    title=attachment.name,
                    body=text,
                    published_at=message.received_at,
                    metadata=metadata,
                )
            ]

        documents = []
        for index, item in enumerate(parsed):
            metadata = self._metadata(message) | item.metadata | {
                "attachment_id": attachment.id,
                "attachment_name": attachment.name,
                "attachment_content_type": attachment.content_type,
                "parser_warnings": ";".join(item.warnings)[:1000],
                "extraction_method": "text_layer",
            }
            documents.append(
                DocumentInput(
                    external_id=f"{message.id}/attachments/{attachment.id}#{index}",
                    title=item.title,
                    body=item.body,
                    published_at=item.published_at or message.received_at,
                    url=item.url,
                    metadata=metadata,
                    pages=item.pages,
                )
            )
        return documents

    def run_once(self) -> dict:
        self.hub.reap_expired_ingestion_leases()
        self.hub.heartbeat_ingestion_worker(
            self.worker_id, self.connector_id, state="idle"
        )
        previous = self.hub.ingestion_checkpoint(self.connector_id)
        cursor = previous["cursor_value"] if previous else ""
        self.hub.start_connector_scan(self.connector_id, "outlook_delta", cursor)
        batch_id = self.hub.create_ingestion_batch(self.connector_id, "outlook_delta")
        groups = []
        page_count = 0
        seen_cursors: set[str] = set()
        final_cursor = cursor
        try:
            while True:
                if page_count >= self.max_pages_per_scan or cursor in seen_cursors:
                    raise ValueError("outlook_delta_pagination_invalid")
                seen_cursors.add(cursor)
                page = self.client.fetch_delta(cursor)
                page_count += 1
                for message in page.messages:
                    metadata = self._metadata(message)
                    attachment_facts = [
                        [item.id, item.name, digest(item.content), item.required]
                        for item in message.attachments
                    ]
                    message_fingerprint = digest(
                        stable_json(
                            [
                                message.change_key,
                                digest(message.body_text),
                                attachment_facts,
                            ]
                        )
                    )
                    parent = self.hub.discover_ingestion_item(
                        batch_id,
                        external_id=message.id,
                        display_name=message.subject or "(no subject)",
                        source_locator=f"{message.folder_id}/{message.id}",
                        content_fingerprint=message_fingerprint,
                        input_bytes=len(message.body_text.encode("utf-8"))
                        + sum(len(item.content) for item in message.attachments),
                        pipeline_version=self.PIPELINE_VERSION,
                        item_kind="email",
                    )
                    children = []
                    for attachment in message.attachments:
                        child = self.hub.discover_ingestion_item(
                            batch_id,
                            external_id=f"{message.id}/attachments/{attachment.id}",
                            display_name=attachment.name,
                            source_locator=f"{message.folder_id}/{message.id}/attachments/{attachment.id}",
                            content_fingerprint=digest(attachment.content),
                            input_bytes=len(attachment.content),
                            pipeline_version=self.PIPELINE_VERSION,
                            parent_item_id=parent["item_id"],
                            item_kind="attachment",
                            required_for_parent=attachment.required,
                        )
                        children.append((attachment, child))
                    groups.append((message, metadata, parent, children))
                if page.next_cursor:
                    cursor = page.next_cursor
                    continue
                if not page.delta_cursor:
                    raise ValueError("outlook_delta_cursor_missing")
                final_cursor = page.delta_cursor
                break
            checkpoint = self.hub.complete_connector_scan(
                self.connector_id, cursor_value=final_cursor
            )
        except (OSError, RuntimeError, ValueError) as exc:
            self.hub.complete_connector_scan(
                self.connector_id,
                cursor_value=previous["cursor_value"] if previous else "",
                error_code=str(exc) or "outlook_delta_failed",
            )
            self.hub.heartbeat_ingestion_worker(
                self.worker_id, self.connector_id, state="stopped"
            )
            raise

        persisted: list[tuple[str, list[str], bool]] = []
        for message, metadata, parent, children in groups:
            parent_detail = self.hub.ingestion_item(parent["item_id"])
            if parent["discovery_outcome"] != "new" and parent_detail["status"] != "retrying":
                continue
            successful_group: list[tuple[str, list[str], bool]] = []
            prepared_children: list[tuple[str, list[DocumentInput]]] = []
            required_failure = False
            try:
                self.hub.start_ingestion_item(parent["item_id"], self.worker_id)
                self.hub.heartbeat_ingestion_worker(
                    self.worker_id,
                    self.connector_id,
                    state="processing",
                    current_item_id=parent["item_id"],
                )
                self.hub.set_ingestion_stage(parent["item_id"], "parse")
                if not message.body_text.strip():
                    raise ValueError("email_has_no_text_body")
                source_id, resolution = self._source(metadata)
                parent_document = DocumentInput(
                    external_id=message.id,
                    title=message.subject or "(no subject)",
                    body=message.body_text.strip(),
                    published_at=message.received_at,
                    metadata=metadata | {"content_type": "email_body"},
                )

                for attachment, child in children:
                    child_detail = self.hub.ingestion_item(child["item_id"])
                    if child["discovery_outcome"] != "new" and child_detail["status"] != "retrying":
                        if attachment.required and child_detail["status"] != "processed":
                            required_failure = True
                        continue
                    try:
                        self.hub.start_ingestion_item(child["item_id"], self.worker_id)
                        self.hub.set_ingestion_stage(child["item_id"], "parse")
                        documents = self._attachment_documents(message, attachment)
                        prepared_children.append((child["item_id"], documents))
                    except (OSError, RuntimeError, ValueError) as exc:
                        self.hub.fail_ingestion_item(
                            child["item_id"],
                            error_class="data",
                            error_code=str(exc) or "attachment_processing_failed",
                            error_message=str(exc) or "attachment_processing_failed",
                            retryable=False,
                        )
                        if attachment.required:
                            required_failure = True

                if required_failure:
                    for item_id, _ in prepared_children:
                        self.hub.fail_ingestion_item(
                            item_id,
                            error_class="dependency",
                            error_code="parent_group_incomplete",
                            error_message="a required sibling attachment failed",
                            retryable=False,
                        )
                    self.hub.fail_ingestion_item(
                        parent["item_id"],
                        error_class="dependency",
                        error_code="required_attachment_failed",
                        error_message="one or more required attachments failed",
                        retryable=False,
                    )
                else:
                    self.hub.set_ingestion_stage(parent["item_id"], "persist")
                    parent_documents = self._persist(
                        source_id, [parent_document], resolution
                    )
                    self.hub.set_ingestion_stage(parent["item_id"], "fts_index")
                    self.hub.set_ingestion_stage(parent["item_id"], "vectorize")
                    successful_group.append((parent["item_id"], parent_documents, True))
                    for item_id, documents in prepared_children:
                        self.hub.set_ingestion_stage(item_id, "persist")
                        document_ids = self._persist(source_id, documents, resolution)
                        self.hub.set_ingestion_stage(item_id, "fts_index")
                        self.hub.set_ingestion_stage(item_id, "vectorize")
                        successful_group.append((item_id, document_ids, False))
                    persisted.extend(successful_group)
            except (OSError, RuntimeError, ValueError) as exc:
                detail = self.hub.ingestion_item(parent["item_id"])
                if detail["status"] == "processing":
                    self.hub.fail_ingestion_item(
                        parent["item_id"],
                        error_class="data",
                        error_code=str(exc) or "email_processing_failed",
                        error_message=str(exc) or "email_processing_failed",
                        retryable=False,
                    )

        semantic_generation = ""
        if persisted:
            try:
                for item_id, _, _ in persisted:
                    self.hub.renew_ingestion_lease(item_id, self.worker_id)
                metadata = self.hub.semantic.build(self.hub.database)
                semantic_generation = str(
                    metadata.get("corpus_digest") or metadata.get("built_at") or ""
                )
                if not semantic_generation:
                    raise RuntimeError("semantic_generation_missing")
                for item_id, document_ids, _ in sorted(
                    persisted, key=lambda item: item[2]
                ):
                    self.hub.set_ingestion_stage(item_id, "publish")
                    self.hub.complete_ingestion_item(
                        item_id, document_ids, semantic_generation
                    )
            except (OSError, RuntimeError, ValueError) as exc:
                for item_id, _, _ in persisted:
                    detail = self.hub.ingestion_item(item_id)
                    if detail["status"] == "processing":
                        self.hub.fail_ingestion_item(
                            item_id,
                            error_class="runtime",
                            error_code=str(exc) or "semantic_build_failed",
                            error_message=str(exc) or "semantic_build_failed",
                            retryable=True,
                        )

        self.hub.finalize_ingestion_batch(batch_id)
        self.hub.heartbeat_ingestion_worker(
            self.worker_id, self.connector_id, state="idle"
        )
        return {
            "batch_id": batch_id,
            "pages": page_count,
            "messages": len(groups),
            "checkpoint": final_cursor,
            "checkpoint_version": checkpoint["state_version"],
            "semantic_generation_id": semantic_generation,
            "summary": self.hub.ingestion_summary(self.connector_id),
        }
