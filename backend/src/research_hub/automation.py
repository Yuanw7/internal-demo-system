from __future__ import annotations

import time
from pathlib import Path

from .cli import ingest_in_batches
from .models import SourceDefinition
from .parsing import PARSER_VERSION, SUPPORTED, SUPPORTED_CONTAINERS, documents_from_path
from .service import RetrievalHub
from .util import digest


class FolderAutomation:
    """Single-host folder discovery and processing using the Hub's durable state tables."""

    PIPELINE_VERSION = f"folder-automation-v1:{PARSER_VERSION}"

    def __init__(
        self,
        hub: RetrievalHub,
        root: Path,
        *,
        connector_id: str,
        connector_name: str,
        source_id: str,
        source_name: str,
        worker_id: str = "local-folder-worker",
        settle_seconds: float = 5.0,
        max_queue_depth: int = 1000,
    ):
        if settle_seconds < 0 or max_queue_depth < 1:
            raise ValueError("invalid_folder_automation_limits")
        self.hub = hub
        self.root = root.resolve()
        self.connector_id = connector_id
        self.source_id = source_id
        self.worker_id = worker_id
        self.settle_seconds = settle_seconds
        self.max_queue_depth = max_queue_depth
        self.hub.upsert_ingestion_connector(
            connector_id,
            connector_name,
            "local_folder",
            config={
                "root_name": self.root.name,
                "settle_seconds": settle_seconds,
                "max_queue_depth": max_queue_depth,
            },
            semantic_required=True,
        )
        self.hub.upsert_source(SourceDefinition(id=source_id, name=source_name, kind="local"))

    def _files(self) -> list[Path]:
        if not self.root.is_dir():
            raise ValueError("input_directory_not_found")
        allowed = SUPPORTED | SUPPORTED_CONTAINERS
        return sorted(path for path in self.root.rglob("*") if path.is_file() and path.suffix.lower() in allowed)

    def run_once(self) -> dict:
        self.hub.reap_expired_ingestion_leases()
        scan_started_at = self.hub.start_connector_scan(self.connector_id, "folder_scan")
        batch_id = self.hub.create_ingestion_batch(self.connector_id, "reconciliation")
        queued: list[tuple[str, Path]] = []
        newly_discovered = 0
        unstable = 0
        backpressured = 0
        observed = 0
        scan_facts: list[str] = []
        self.hub.heartbeat_ingestion_worker(
            self.worker_id, self.connector_id, state="idle"
        )
        try:
            for path in self._files():
                relative = path.relative_to(self.root).as_posix()
                stat_before = path.stat()
                observed += 1
                scan_facts.append(f"{relative}:{stat_before.st_size}:{stat_before.st_mtime_ns}")
                observation = self.hub.observe_source_object(
                    self.connector_id,
                    relative,
                    size_bytes=stat_before.st_size,
                    mtime_ns=stat_before.st_mtime_ns,
                    settle_seconds=self.settle_seconds,
                )
                if not observation["stable"]:
                    unstable += 1
                    continue
                if self.hub.ingestion_queue_depth(self.connector_id) >= self.max_queue_depth:
                    backpressured += 1
                    self.hub.heartbeat_ingestion_worker(
                        self.worker_id, self.connector_id, state="backpressured"
                    )
                    continue
                raw = path.read_bytes()
                stat_after = path.stat()
                if (
                    stat_after.st_size != stat_before.st_size
                    or stat_after.st_mtime_ns != stat_before.st_mtime_ns
                ):
                    self.hub.observe_source_object(
                        self.connector_id,
                        relative,
                        size_bytes=stat_after.st_size,
                        mtime_ns=stat_after.st_mtime_ns,
                        settle_seconds=self.settle_seconds,
                    )
                    unstable += 1
                    continue
                fingerprint = digest(raw)
                if observation["last_enqueued_fingerprint"] == fingerprint:
                    continue
                result = self.hub.discover_ingestion_item(
                    batch_id,
                    external_id=relative,
                    display_name=path.name,
                    source_locator=relative,
                    content_fingerprint=fingerprint,
                    input_bytes=len(raw),
                    pipeline_version=self.PIPELINE_VERSION,
                )
                self.hub.mark_source_object_enqueued(
                    self.connector_id, relative, fingerprint
                )
                detail = self.hub.ingestion_item(result["item_id"])
                if result["discovery_outcome"] == "new":
                    newly_discovered += 1
                    queued.append((result["item_id"], path))
                elif detail["status"] == "retrying":
                    queued.append((result["item_id"], path))

            deleted_observed = self.hub.mark_unseen_source_objects_deleted(
                self.connector_id, scan_started_at
            )
            checkpoint = self.hub.complete_connector_scan(
                self.connector_id, cursor_value=digest("\n".join(scan_facts))
            )
        except (OSError, RuntimeError, ValueError) as exc:
            self.hub.complete_connector_scan(
                self.connector_id, error_code=str(exc) or "folder_scan_failed"
            )
            self.hub.heartbeat_ingestion_worker(
                self.worker_id, self.connector_id, state="stopped"
            )
            raise

        persisted: list[tuple[str, list[str]]] = []
        for item_id, path in queued:
            try:
                self.hub.start_ingestion_item(item_id, self.worker_id)
                self.hub.heartbeat_ingestion_worker(
                    self.worker_id,
                    self.connector_id,
                    state="processing",
                    current_item_id=item_id,
                )
                self.hub.set_ingestion_stage(item_id, "parse")
                documents, errors = documents_from_path(path)
                if errors or not documents:
                    code = errors[0]["error"] if errors else "no_documents_parsed"
                    self.hub.fail_ingestion_item(
                        item_id,
                        error_class="data",
                        error_code=code,
                        error_message=code,
                        retryable=False,
                    )
                    continue
                self.hub.renew_ingestion_lease(item_id, self.worker_id)
                self.hub.set_ingestion_stage(item_id, "persist")
                result = ingest_in_batches(self.hub, self.source_id, documents)
                self.hub.set_ingestion_stage(item_id, "fts_index")
                self.hub.set_ingestion_stage(item_id, "vectorize")
                persisted.append((item_id, result["document_ids"]))
            except (OSError, RuntimeError, ValueError) as exc:
                try:
                    self.hub.fail_ingestion_item(
                        item_id,
                        error_class="runtime",
                        error_code=str(exc) or "processing_failed",
                        error_message=str(exc) or "processing_failed",
                        retryable=True,
                    )
                except ValueError:
                    pass

        semantic_generation = ""
        if persisted:
            try:
                for item_id, _ in persisted:
                    self.hub.renew_ingestion_lease(item_id, self.worker_id)
                metadata = self.hub.semantic.build(self.hub.database)
                semantic_generation = str(metadata.get("corpus_digest") or metadata.get("built_at") or "")
                if not semantic_generation:
                    raise RuntimeError("semantic_generation_missing")
                for item_id, document_ids in persisted:
                    self.hub.set_ingestion_stage(item_id, "publish")
                    self.hub.complete_ingestion_item(item_id, document_ids, semantic_generation)
            except (OSError, RuntimeError, ValueError) as exc:
                for item_id, _ in persisted:
                    try:
                        self.hub.fail_ingestion_item(
                            item_id,
                            error_class="runtime",
                            error_code=str(exc) or "semantic_build_failed",
                            error_message=str(exc) or "semantic_build_failed",
                            retryable=True,
                        )
                    except ValueError:
                        pass

        self.hub.finalize_ingestion_batch(batch_id)
        self.hub.heartbeat_ingestion_worker(
            self.worker_id, self.connector_id, state="idle"
        )

        return {
            "batch_id": batch_id,
            "observed": observed,
            "discovered": newly_discovered,
            "unstable": unstable,
            "backpressured": backpressured,
            "deleted_observed": deleted_observed,
            "checkpoint_version": checkpoint["state_version"],
            "semantic_generation_id": semantic_generation,
            "summary": self.hub.ingestion_summary(self.connector_id),
        }

    def run_forever(self, interval_seconds: float) -> None:
        if interval_seconds <= 0:
            raise ValueError("invalid_poll_interval")
        try:
            while True:
                self.run_once()
                time.sleep(interval_seconds)
        finally:
            self.hub.heartbeat_ingestion_worker(
                self.worker_id, self.connector_id, state="stopped"
            )
