from __future__ import annotations

import json
import math
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from .chunking import chunk_document
from .database import Database
from .models import (
    DocumentInput,
    IngestRequest,
    PolicyUpdate,
    RetrievalPolicy,
    SearchRequest,
    SourceDefinition,
)
from .query_planner import plan_query
from .semantic import SemanticIndex
from .source_ranking import (
    PrimarySourceResolution,
    SourceRankingCatalog,
    normalize_source_name,
)
from .util import digest, search_tokens, stable_json, utcnow


class HubError(ValueError):
    pass


class RetrievalHub:
    def __init__(
        self,
        directory: Path,
        base_url: str = "http://127.0.0.1:8765",
        semantic_index=None,
    ):
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.query or parsed.fragment:
            raise HubError("invalid_base_url")
        self.database = Database(directory)
        self.base_url = base_url.rstrip("/")
        self.semantic = semantic_index or SemanticIndex(directory)

    def upsert_source(self, source: SourceDefinition) -> dict:
        now = utcnow()
        with self.database.connection() as connection:
            connection.execute(
                "INSERT INTO sources VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name,kind=excluded.kind,"
                "enabled=excluded.enabled,updated_at=excluded.updated_at",
                (source.id, source.name, source.kind, int(source.enabled), now, now),
            )
        return source.model_dump()

    def sources(self) -> list[dict]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT s.id,s.name,s.kind,s.enabled,s.updated_at,count(d.id) document_count "
                "FROM sources s LEFT JOIN documents d ON d.source_id=s.id "
                "GROUP BY s.id ORDER BY s.id"
            ).fetchall()
        return [dict(row) | {"enabled": bool(row["enabled"])} for row in rows]

    def sync_information_source_catalog(
        self, catalog: SourceRankingCatalog, *, retrieval_kind: str = "demo"
    ) -> dict:
        now = utcnow()
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for source in catalog.sources.values():
                connection.execute(
                    "INSERT INTO information_sources VALUES(?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET display_name=excluded.display_name,"
                    "source_type=excluded.source_type,priority_tier=excluded.priority_tier,"
                    "enabled=excluded.enabled,catalog_version=excluded.catalog_version,"
                    "updated_at=excluded.updated_at",
                    (
                        source.id,
                        source.display_name,
                        source.source_type,
                        source.priority_tier,
                        1,
                        catalog.version,
                        now,
                        now,
                    ),
                )
                connection.execute(
                    "INSERT INTO sources VALUES(?,?,?,?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET name=excluded.name,kind=excluded.kind,"
                    "enabled=excluded.enabled,updated_at=excluded.updated_at",
                    (source.id, source.display_name, retrieval_kind, 1, now, now),
                )
                connection.execute(
                    "DELETE FROM information_source_aliases WHERE source_id=?", (source.id,)
                )
                labels = [(source.display_name, "canonical"), *[(a, "explicit") for a in source.aliases]]
                for alias, alias_type in labels:
                    connection.execute(
                        "INSERT OR IGNORE INTO information_source_aliases("
                        "source_id,alias,normalized_alias,alias_type,created_at) VALUES(?,?,?,?,?)",
                        (
                            source.id,
                            alias,
                            normalize_source_name(alias),
                            alias_type,
                            now,
                        ),
                    )
            ambiguous = connection.execute(
                "SELECT count(*) FROM (SELECT normalized_alias FROM information_source_aliases "
                "GROUP BY normalized_alias HAVING count(DISTINCT source_id)>1)"
            ).fetchone()[0]
        return {
            "catalog_version": catalog.version,
            "sources": len(catalog.sources),
            "ambiguous_aliases": ambiguous,
        }

    def information_sources(self) -> list[dict]:
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT i.id,i.display_name,i.source_type,i.priority_tier,i.enabled,"
                "i.catalog_version,count(DISTINCT a.version_id) attributed_versions "
                "FROM information_sources i LEFT JOIN document_source_attributions a "
                "ON a.information_source_id=i.id GROUP BY i.id ORDER BY i.priority_tier,i.id"
            ).fetchall()
        return [dict(row) | {"enabled": bool(row["enabled"])} for row in rows]

    def upsert_ingestion_connector(
        self,
        connector_id: str,
        name: str,
        kind: str,
        *,
        config: dict | None = None,
        semantic_required: bool = True,
        processing_priority: int = 0,
    ) -> dict:
        if kind not in {"local_folder", "outlook"}:
            raise HubError("invalid_ingestion_connector_kind")
        if not connector_id or not name:
            raise HubError("invalid_ingestion_connector")
        now = utcnow()
        config_json = stable_json(config or {})
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO ingestion_connectors VALUES(?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name,kind=excluded.kind,"
                "config_json=excluded.config_json,semantic_required=excluded.semantic_required,"
                "processing_priority=excluded.processing_priority,state_version=state_version+1,"
                "updated_at=excluded.updated_at",
                (
                    connector_id,
                    name,
                    kind,
                    1,
                    config_json,
                    int(semantic_required),
                    processing_priority,
                    1,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM ingestion_connectors WHERE id=?", (connector_id,)
            ).fetchone()
        result = dict(row)
        result["enabled"] = bool(result["enabled"])
        result["semantic_required"] = bool(result["semantic_required"])
        result["config"] = json.loads(result.pop("config_json"))
        return result

    def create_ingestion_batch(self, connector_id: str, trigger_kind: str) -> str:
        if trigger_kind not in {"poll", "manual", "reconciliation", "outlook_delta"}:
            raise HubError("invalid_ingestion_trigger")
        now = utcnow()
        batch_id = digest(f"{connector_id}:{trigger_kind}:{now}:{time.time_ns()}")[:32]
        with self.database.connection() as connection:
            if not connection.execute(
                "SELECT 1 FROM ingestion_connectors WHERE id=? AND enabled=1", (connector_id,)
            ).fetchone():
                raise HubError("ingestion_connector_not_found")
            connection.execute(
                "INSERT INTO ingestion_batches VALUES(?,?,?,'pending',0,0,0,0,0,1,?,?,?,?)",
                (batch_id, connector_id, trigger_kind, now, "", "", now),
            )
        return batch_id

    def start_connector_scan(
        self, connector_id: str, cursor_kind: str, cursor_value: str = ""
    ) -> str:
        """Persist the scan boundary before discovery so restart state is explicit."""
        if not cursor_kind:
            raise HubError("invalid_ingestion_cursor_kind")
        now = datetime.now(UTC).isoformat(timespec="microseconds")
        with self.database.connection() as connection:
            if not connection.execute(
                "SELECT 1 FROM ingestion_connectors WHERE id=? AND enabled=1", (connector_id,)
            ).fetchone():
                raise HubError("ingestion_connector_not_found")
            connection.execute(
                "INSERT INTO ingestion_checkpoints VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(connector_id) DO UPDATE SET cursor_kind=excluded.cursor_kind,"
                "last_scan_started_at=excluded.last_scan_started_at,last_error_code='',"
                "state_version=state_version+1,updated_at=excluded.updated_at",
                (connector_id, cursor_kind, cursor_value, now, "", "", 1, now),
            )
        return now

    def complete_connector_scan(
        self,
        connector_id: str,
        *,
        cursor_value: str = "",
        error_code: str = "",
    ) -> dict:
        now = utcnow()
        with self.database.connection() as connection:
            changed = connection.execute(
                "UPDATE ingestion_checkpoints SET cursor_value=?,"
                "last_scan_succeeded_at=CASE WHEN ?='' THEN ? ELSE last_scan_succeeded_at END,"
                "last_error_code=?,state_version=state_version+1,updated_at=? WHERE connector_id=?",
                (cursor_value, error_code, now, error_code, now, connector_id),
            ).rowcount
            if not changed:
                raise HubError("ingestion_checkpoint_not_found")
            row = connection.execute(
                "SELECT * FROM ingestion_checkpoints WHERE connector_id=?", (connector_id,)
            ).fetchone()
        return dict(row)

    def ingestion_checkpoint(self, connector_id: str) -> dict | None:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM ingestion_checkpoints WHERE connector_id=?", (connector_id,)
            ).fetchone()
        return dict(row) if row else None

    def observe_source_object(
        self,
        connector_id: str,
        external_id: str,
        *,
        size_bytes: int,
        mtime_ns: int,
        settle_seconds: float,
    ) -> dict:
        if not external_id or size_bytes < 0 or mtime_ns < 0 or settle_seconds < 0:
            raise HubError("invalid_source_object_observation")
        now_dt = datetime.now(UTC)
        now = now_dt.isoformat(timespec="microseconds")
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM ingestion_source_objects WHERE connector_id=? AND external_id=?",
                (connector_id, external_id),
            ).fetchone()
            changed = row is None or row["size_bytes"] != size_bytes or row["mtime_ns"] != mtime_ns
            if row is None:
                connection.execute(
                    "INSERT INTO ingestion_source_objects VALUES(?,?,?,?,?,?,?,?,?,NULL)",
                    (connector_id, external_id, size_bytes, mtime_ns, "", now, now, now, ""),
                )
                stable_since = now
                last_enqueued = ""
            elif changed:
                connection.execute(
                    "UPDATE ingestion_source_objects SET size_bytes=?,mtime_ns=?,content_fingerprint='',"
                    "last_seen_at=?,stable_since=?,deleted_at=NULL WHERE connector_id=? AND external_id=?",
                    (size_bytes, mtime_ns, now, now, connector_id, external_id),
                )
                stable_since = now
                last_enqueued = row["last_enqueued_fingerprint"]
            else:
                connection.execute(
                    "UPDATE ingestion_source_objects SET last_seen_at=?,deleted_at=NULL "
                    "WHERE connector_id=? AND external_id=?",
                    (now, connector_id, external_id),
                )
                stable_since = row["stable_since"]
                last_enqueued = row["last_enqueued_fingerprint"]
        stable_age = max(
            0.0, (now_dt - datetime.fromisoformat(stable_since)).total_seconds()
        )
        return {
            "stable": stable_age >= settle_seconds,
            "changed": changed,
            "stable_since": stable_since,
            "last_enqueued_fingerprint": last_enqueued,
        }

    def mark_source_object_enqueued(
        self, connector_id: str, external_id: str, content_fingerprint: str
    ) -> None:
        if not content_fingerprint:
            raise HubError("invalid_content_fingerprint")
        with self.database.connection() as connection:
            changed = connection.execute(
                "UPDATE ingestion_source_objects SET content_fingerprint=?,"
                "last_enqueued_fingerprint=? "
                "WHERE connector_id=? AND external_id=?",
                (content_fingerprint, content_fingerprint, connector_id, external_id),
            ).rowcount
            if not changed:
                raise HubError("source_object_not_found")

    def mark_unseen_source_objects_deleted(self, connector_id: str, scan_started_at: str) -> int:
        now = utcnow()
        with self.database.connection() as connection:
            return connection.execute(
                "UPDATE ingestion_source_objects SET deleted_at=? WHERE connector_id=? "
                "AND last_seen_at<? AND deleted_at IS NULL",
                (now, connector_id, scan_started_at),
            ).rowcount

    def ingestion_queue_depth(self, connector_id: str) -> int:
        with self.database.connection() as connection:
            return connection.execute(
                "SELECT count(*) FROM ingestion_items WHERE connector_id=? "
                "AND status IN ('pending','processing','retrying')",
                (connector_id,),
            ).fetchone()[0]

    def heartbeat_ingestion_worker(
        self,
        worker_id: str,
        connector_id: str,
        *,
        state: str,
        current_item_id: str | None = None,
    ) -> None:
        if state not in {"idle", "processing", "backpressured", "stopped"}:
            raise HubError("invalid_worker_state")
        now = utcnow()
        with self.database.connection() as connection:
            connection.execute(
                "INSERT INTO ingestion_worker_heartbeats VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(worker_id) DO UPDATE SET connector_id=excluded.connector_id,"
                "current_item_id=excluded.current_item_id,state=excluded.state,"
                "last_seen_at=excluded.last_seen_at,updated_at=excluded.updated_at",
                (worker_id, connector_id, current_item_id, state, now, now),
            )

    def renew_ingestion_lease(self, item_id: str, worker_id: str, lease_seconds: int = 300) -> None:
        if lease_seconds < 1:
            raise HubError("invalid_ingestion_lease")
        expires = (datetime.now(UTC) + timedelta(seconds=lease_seconds)).isoformat(timespec="seconds")
        now = utcnow()
        with self.database.connection() as connection:
            changed = connection.execute(
                "UPDATE ingestion_items SET lease_expires_at=?,updated_at=? WHERE id=? "
                "AND status='processing' AND lease_owner=?",
                (expires, now, item_id, worker_id),
            ).rowcount
            if not changed:
                raise HubError("ingestion_lease_not_owned")
        self.heartbeat_ingestion_worker(
            worker_id, self.ingestion_item(item_id)["connector_id"], state="processing", current_item_id=item_id
        )

    def discover_ingestion_item(
        self,
        batch_id: str,
        *,
        external_id: str,
        display_name: str,
        source_locator: str,
        content_fingerprint: str,
        input_bytes: int,
        pipeline_version: str,
        max_attempts: int = 3,
        parent_item_id: str | None = None,
        item_kind: str = "document",
        required_for_parent: bool = False,
    ) -> dict:
        if (
            not external_id
            or not display_name
            or not content_fingerprint
            or max_attempts < 1
            or item_kind not in {"document", "email", "attachment"}
        ):
            raise HubError("invalid_ingestion_item")
        now = utcnow()
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            batch = connection.execute(
                "SELECT b.connector_id,c.semantic_required,c.processing_priority "
                "FROM ingestion_batches b JOIN ingestion_connectors c ON c.id=b.connector_id "
                "WHERE b.id=?",
                (batch_id,),
            ).fetchone()
            if batch is None:
                raise HubError("ingestion_batch_not_found")
            key = digest(
                stable_json(
                    [batch["connector_id"], external_id, content_fingerprint, pipeline_version]
                )
            )
            item_id = digest(f"ingestion:{key}")[:32]
            existed = connection.execute(
                "SELECT 1 FROM ingestion_items WHERE connector_id=? AND idempotency_key=?",
                (batch["connector_id"], key),
            ).fetchone()
            connection.execute(
                "INSERT OR IGNORE INTO ingestion_items("
                "id,connector_id,external_id,display_name,source_locator,content_fingerprint,"
                "pipeline_version,idempotency_key,status,pipeline_stage,outcome,semantic_required,"
                "processing_priority,attempt_count,max_attempts,eligible_at,next_attempt_at,"
                "lease_owner,lease_expires_at,discovered_at,started_at,searchable_at,finished_at,"
                "updated_at,document_ids_json,semantic_generation_id,input_bytes,duration_ms,"
                "error_class,error_code,error_message,state_version) "
                "VALUES(?,?,?,?,?,?,?,?,'pending','discovered','',?,?,0,?,?,NULL,NULL,NULL,?,NULL,NULL,NULL,"
                "?,'[]',NULL,?,NULL,'','','',1)",
                (
                    item_id,
                    batch["connector_id"],
                    external_id,
                    display_name,
                    source_locator,
                    content_fingerprint,
                    pipeline_version,
                    key,
                    batch["semantic_required"],
                    batch["processing_priority"],
                    max_attempts,
                    now,
                    now,
                    now,
                    input_bytes,
                ),
            )
            if not existed:
                connection.execute(
                    "UPDATE ingestion_items SET parent_item_id=?,item_kind=?,required_for_parent=? "
                    "WHERE id=?",
                    (parent_item_id, item_kind, int(required_for_parent), item_id),
                )
            connection.execute(
                "INSERT OR IGNORE INTO ingestion_batch_items VALUES(?,?,?)",
                (batch_id, item_id, "already_known" if existed else "new"),
            )
            connection.execute(
                "UPDATE ingestion_batches SET discovered_count=(SELECT count(*) FROM ingestion_batch_items "
                "WHERE batch_id=?),updated_at=? WHERE id=?",
                (batch_id, now, batch_id),
            )
        return {"item_id": item_id, "discovery_outcome": "already_known" if existed else "new"}

    def start_ingestion_item(self, item_id: str, worker_id: str, lease_seconds: int = 300) -> dict:
        now_dt = datetime.now(UTC)
        now = now_dt.isoformat(timespec="seconds")
        expires = (now_dt + timedelta(seconds=lease_seconds)).isoformat(timespec="seconds")
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status,attempt_count,max_attempts,eligible_at,next_attempt_at "
                "FROM ingestion_items WHERE id=?", (item_id,)
            ).fetchone()
            if row is None:
                raise HubError("ingestion_item_not_found")
            if row["status"] not in {"pending", "retrying"}:
                raise HubError("ingestion_item_not_claimable")
            if row["eligible_at"] > now or (row["next_attempt_at"] and row["next_attempt_at"] > now):
                raise HubError("ingestion_item_not_ready")
            if row["attempt_count"] >= row["max_attempts"]:
                raise HubError("ingestion_attempts_exhausted")
            attempt = row["attempt_count"] + 1
            connection.execute(
                "UPDATE ingestion_items SET status='processing',pipeline_stage='fetch',"
                "attempt_count=?,lease_owner=?,lease_expires_at=?,started_at=coalesce(started_at,?),"
                "updated_at=?,state_version=state_version+1 WHERE id=?",
                (attempt, worker_id, expires, now, now, item_id),
            )
            connection.execute(
                "INSERT INTO ingestion_attempts(item_id,attempt_number,worker_id,started_at,finished_at,"
                "outcome,error_class,error_code,duration_ms) VALUES(?,?,?,? ,NULL,'running','','',NULL)",
                (item_id, attempt, worker_id, now),
            )
            version = connection.execute(
                "SELECT state_version FROM ingestion_items WHERE id=?", (item_id,)
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO ingestion_status_events(item_id,from_status,to_status,pipeline_stage,"
                "state_version,actor_type,actor_id,reason,occurred_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (item_id, row["status"], "processing", "fetch", version, "worker", worker_id, "claimed", now),
            )
        return self.ingestion_item(item_id)

    def reap_expired_ingestion_leases(self) -> int:
        now = utcnow()
        with self.database.connection() as connection:
            item_ids = [
                row[0]
                for row in connection.execute(
                    "SELECT id FROM ingestion_items WHERE status='processing' "
                    "AND lease_expires_at IS NOT NULL AND lease_expires_at<=?",
                    (now,),
                )
            ]
        for item_id in item_ids:
            self.fail_ingestion_item(
                item_id,
                error_class="runtime",
                error_code="worker_lease_expired",
                error_message="worker lease expired before completion",
                retryable=True,
            )
        return len(item_ids)

    def set_ingestion_stage(self, item_id: str, stage: str) -> None:
        if stage not in {"fetch", "parse", "persist", "fts_index", "vectorize", "publish"}:
            raise HubError("invalid_ingestion_stage")
        with self.database.connection() as connection:
            changed = connection.execute(
                "UPDATE ingestion_items SET pipeline_stage=?,updated_at=?,state_version=state_version+1 "
                "WHERE id=? AND status='processing'",
                (stage, utcnow(), item_id),
            ).rowcount
            if not changed:
                raise HubError("ingestion_item_not_processing")

    def complete_ingestion_item(
        self, item_id: str, document_ids: list[str], semantic_generation_id: str
    ) -> dict:
        now = utcnow()
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status,semantic_required,attempt_count,started_at,state_version "
                "FROM ingestion_items WHERE id=?",
                (item_id,),
            ).fetchone()
            if row is None:
                raise HubError("ingestion_item_not_found")
            if row["status"] != "processing":
                raise HubError("ingestion_item_not_processing")
            if row["semantic_required"] and not semantic_generation_id:
                raise HubError("semantic_generation_required")
            duration = max(
                0,
                int(
                    (
                        datetime.fromisoformat(now)
                        - datetime.fromisoformat(row["started_at"])
                    ).total_seconds()
                    * 1000
                ),
            )
            version = row["state_version"] + 1
            connection.execute(
                "UPDATE ingestion_items SET status='processed',pipeline_stage='publish',outcome='indexed',"
                "searchable_at=?,finished_at=?,updated_at=?,document_ids_json=?,semantic_generation_id=?,"
                "duration_ms=?,lease_owner=NULL,lease_expires_at=NULL,error_class='',error_code='',"
                "error_message='',state_version=? WHERE id=?",
                (now, now, now, stable_json(document_ids), semantic_generation_id or None, duration, version, item_id),
            )
            connection.execute(
                "UPDATE ingestion_attempts SET finished_at=?,outcome='processed',duration_ms=? "
                "WHERE item_id=? AND attempt_number=?",
                (now, duration, item_id, row["attempt_count"]),
            )
            connection.execute(
                "INSERT INTO ingestion_status_events(item_id,from_status,to_status,pipeline_stage,"
                "state_version,actor_type,actor_id,reason,occurred_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (item_id, "processing", "processed", "publish", version, "worker", "local", "published", now),
            )
        self._refresh_ingestion_batches(item_id)
        return self.ingestion_item(item_id)

    def fail_ingestion_item(
        self,
        item_id: str,
        *,
        error_class: str,
        error_code: str,
        error_message: str,
        retryable: bool,
    ) -> dict:
        now_dt = datetime.now(UTC)
        now = now_dt.isoformat(timespec="seconds")
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status,pipeline_stage,attempt_count,max_attempts,state_version "
                "FROM ingestion_items WHERE id=?",
                (item_id,),
            ).fetchone()
            if row is None:
                raise HubError("ingestion_item_not_found")
            if row["status"] != "processing":
                raise HubError("ingestion_item_not_processing")
            will_retry = retryable and row["attempt_count"] < row["max_attempts"]
            status = "retrying" if will_retry else "failed"
            next_attempt = (
                (now_dt + timedelta(seconds=min(300, 2 ** row["attempt_count"]))).isoformat(timespec="seconds")
                if will_retry
                else None
            )
            version = row["state_version"] + 1
            connection.execute(
                "UPDATE ingestion_items SET status=?,next_attempt_at=?,finished_at=?,updated_at=?,"
                "lease_owner=NULL,lease_expires_at=NULL,error_class=?,error_code=?,error_message=?,"
                "state_version=? WHERE id=?",
                (status, next_attempt, now, now, error_class, error_code, error_message[:1000], version, item_id),
            )
            connection.execute(
                "UPDATE ingestion_attempts SET finished_at=?,outcome=?,error_class=?,error_code=? "
                "WHERE item_id=? AND attempt_number=?",
                (now, status, error_class, error_code, item_id, row["attempt_count"]),
            )
            connection.execute(
                "INSERT INTO ingestion_status_events(item_id,from_status,to_status,pipeline_stage,"
                "state_version,actor_type,actor_id,reason,occurred_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (item_id, "processing", status, row["pipeline_stage"], version, "worker", "local", error_code, now),
            )
            if status == "failed":
                connection.execute(
                    "INSERT INTO ingestion_dead_letters VALUES(?,?,?,?,?,NULL,'') "
                    "ON CONFLICT(item_id) DO UPDATE SET terminal_reason=excluded.terminal_reason,"
                    "failed_stage=excluded.failed_stage,last_attempt_number=excluded.last_attempt_number,"
                    "created_at=excluded.created_at,resolved_at=NULL,resolution_note=''",
                    (item_id, error_code, row["pipeline_stage"], row["attempt_count"], now),
                )
        self._refresh_ingestion_batches(item_id)
        return self.ingestion_item(item_id)

    def retry_ingestion_item(
        self, item_id: str, expected_state_version: int, reason: str, mode: str
    ) -> dict:
        if mode not in {"resume_failed_stage", "restart"} or not reason.strip():
            raise HubError("invalid_ingestion_retry")
        now = utcnow()
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status,state_version,pipeline_stage FROM ingestion_items WHERE id=?", (item_id,)
            ).fetchone()
            if row is None:
                raise HubError("ingestion_item_not_found")
            if row["state_version"] != expected_state_version:
                raise HubError("ingestion_state_version_conflict")
            if row["status"] not in {"failed", "retrying"}:
                raise HubError("ingestion_item_not_retryable")
            stage = "fetch" if mode == "restart" else row["pipeline_stage"]
            version = row["state_version"] + 1
            connection.execute(
                "UPDATE ingestion_items SET status='retrying',pipeline_stage=?,next_attempt_at=?,"
                "finished_at=NULL,updated_at=?,error_class='',error_code='',error_message='',"
                "state_version=? WHERE id=?",
                (stage, now, now, version, item_id),
            )
            connection.execute(
                "UPDATE ingestion_dead_letters SET resolved_at=?,resolution_note=? WHERE item_id=?",
                (now, reason[:500], item_id),
            )
            connection.execute(
                "INSERT INTO ingestion_status_events(item_id,from_status,to_status,pipeline_stage,"
                "state_version,actor_type,actor_id,reason,occurred_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (item_id, row["status"], "retrying", stage, version, "admin", "local", reason[:500], now),
            )
        self._refresh_ingestion_batches(item_id)
        return {"item_id": item_id, "status": "retrying", "next_attempt_at": now, "state_version": version}

    def _refresh_ingestion_batches(self, item_id: str) -> None:
        now = utcnow()
        with self.database.connection() as connection:
            batch_ids = [
                row[0]
                for row in connection.execute(
                    "SELECT batch_id FROM ingestion_batch_items WHERE item_id=?", (item_id,)
                )
            ]
            for batch_id in batch_ids:
                counts = {
                    row["status"]: row["count"]
                    for row in connection.execute(
                        "SELECT i.status,count(*) count FROM ingestion_items i "
                        "JOIN ingestion_batch_items bi ON bi.item_id=i.id WHERE bi.batch_id=? "
                        "GROUP BY i.status",
                        (batch_id,),
                    )
                }
                total = sum(counts.values())
                if total and counts.get("processed", 0) == total:
                    status, finished = "processed", now
                elif counts.get("processing", 0) or counts.get("pending", 0):
                    status, finished = "processing", ""
                elif counts.get("retrying", 0):
                    status, finished = "retrying", ""
                elif counts.get("failed", 0):
                    status, finished = "failed", now
                else:
                    status, finished = "pending", ""
                connection.execute(
                    "UPDATE ingestion_batches SET status=?,processed_count=?,failed_count=?,"
                    "retrying_count=?,finished_at=?,updated_at=?,state_version=state_version+1 "
                    "WHERE id=?",
                    (
                        status,
                        counts.get("processed", 0),
                        counts.get("failed", 0),
                        counts.get("retrying", 0),
                        finished,
                        now,
                        batch_id,
                    ),
                )

    def finalize_ingestion_batch(self, batch_id: str) -> dict:
        """Close an empty/unchanged batch or recompute its terminal state."""
        with self.database.connection() as connection:
            item = connection.execute(
                "SELECT item_id FROM ingestion_batch_items WHERE batch_id=? LIMIT 1", (batch_id,)
            ).fetchone()
            if item is None:
                now = utcnow()
                changed = connection.execute(
                    "UPDATE ingestion_batches SET status='processed',finished_at=?,updated_at=?,"
                    "state_version=state_version+1 WHERE id=?",
                    (now, now, batch_id),
                ).rowcount
                if not changed:
                    raise HubError("ingestion_batch_not_found")
            else:
                item_id = item["item_id"]
        if item is not None:
            self._refresh_ingestion_batches(item_id)
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM ingestion_batches WHERE id=?", (batch_id,)
            ).fetchone()
        return dict(row)

    @staticmethod
    def _ingestion_summary_row(row) -> dict:
        return {
            "id": row["id"],
            "connector_id": row["connector_id"],
            "external_id": row["external_id"],
            "display_name": row["display_name"],
            "status": row["status"],
            "pipeline_stage": row["pipeline_stage"],
            "outcome": row["outcome"],
            "attempt_count": row["attempt_count"],
            "max_attempts": row["max_attempts"],
            "discovered_at": row["discovered_at"],
            "started_at": row["started_at"],
            "searchable_at": row["searchable_at"],
            "finished_at": row["finished_at"],
            "error_code": row["error_code"],
            "state_version": row["state_version"],
        }

    def ingestion_summary(self, connector_id: str = "") -> dict:
        where = " WHERE connector_id=?" if connector_id else ""
        params = (connector_id,) if connector_id else ()
        now = datetime.now(UTC)
        with self.database.connection() as connection:
            counts = {status: 0 for status in ("pending", "processing", "processed", "failed", "retrying")}
            for row in connection.execute(
                "SELECT status,count(*) count FROM ingestion_items" + where + " GROUP BY status", params
            ):
                counts[row["status"]] = row["count"]
            vector_backlog = connection.execute(
                "SELECT count(*) FROM ingestion_items" + where + (" AND" if where else " WHERE")
                + " semantic_required=1 AND status!='processed' AND pipeline_stage IN ('vectorize','publish')",
                params,
            ).fetchone()[0]
            dead_where = (
                " WHERE d.resolved_at IS NULL AND i.connector_id=?"
                if connector_id
                else " WHERE d.resolved_at IS NULL"
            )
            dead = connection.execute(
                "SELECT count(*) FROM ingestion_dead_letters d JOIN ingestion_items i ON i.id=d.item_id"
                + dead_where,
                params,
            ).fetchone()[0]
            oldest = connection.execute(
                "SELECT min(discovered_at) FROM ingestion_items" + where + (" AND" if where else " WHERE")
                + " status IN ('pending','retrying')",
                params,
            ).fetchone()[0]
        age = max(0.0, (now - datetime.fromisoformat(oldest)).total_seconds()) if oldest else None
        return {
            "as_of": now.isoformat(timespec="seconds"),
            "counts": counts,
            "vector_backlog": vector_backlog,
            "unresolved_dead_letters": dead,
            "oldest_pending_age_seconds": age,
        }

    def ingestion_items(
        self,
        *,
        status: str = "",
        connector_id: str = "",
        pipeline_stage: str = "",
        limit: int = 50,
        cursor: str = "",
    ) -> dict:
        if not 1 <= limit <= 100:
            raise HubError("invalid_ingestion_limit")
        clauses, params = [], []
        if status:
            clauses.append("status=?")
            params.append(status)
        if connector_id:
            clauses.append("connector_id=?")
            params.append(connector_id)
        if pipeline_stage:
            clauses.append("pipeline_stage=?")
            params.append(pipeline_stage)
        if cursor:
            try:
                cursor_time, cursor_id = json.loads(urlsafe_b64decode(cursor + "==").decode("utf-8"))
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise HubError("invalid_ingestion_cursor") from exc
            clauses.append("(discovered_at<? OR (discovered_at=? AND id<?))")
            params.extend([cursor_time, cursor_time, cursor_id])
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.database.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM ingestion_items" + where + " ORDER BY discovered_at DESC,id DESC LIMIT ?",
                [*params, limit + 1],
            ).fetchall()
        page = rows[:limit]
        next_cursor = None
        if len(rows) > limit:
            last = page[-1]
            next_cursor = urlsafe_b64encode(
                stable_json([last["discovered_at"], last["id"]]).encode("utf-8")
            ).decode("ascii").rstrip("=")
        return {"items": [self._ingestion_summary_row(row) for row in page], "next_cursor": next_cursor}

    def ingestion_item(self, item_id: str) -> dict:
        with self.database.connection() as connection:
            row = connection.execute("SELECT * FROM ingestion_items WHERE id=?", (item_id,)).fetchone()
            if row is None:
                raise HubError("ingestion_item_not_found")
            attempts = [
                dict(item)
                for item in connection.execute(
                    "SELECT attempt_number,worker_id,started_at,finished_at,outcome,error_class,"
                    "error_code,duration_ms FROM ingestion_attempts WHERE item_id=? ORDER BY attempt_number",
                    (item_id,),
                )
            ]
            events = [
                dict(item)
                for item in connection.execute(
                    "SELECT id,from_status,to_status,pipeline_stage,actor_type,actor_id,reason,occurred_at "
                    "FROM ingestion_status_events WHERE item_id=? ORDER BY id",
                    (item_id,),
                )
            ]
        result = self._ingestion_summary_row(row)
        result.update(
            {
                "source_locator": row["source_locator"],
                "content_fingerprint": row["content_fingerprint"],
                "pipeline_version": row["pipeline_version"],
                "semantic_required": bool(row["semantic_required"]),
                "semantic_generation_id": row["semantic_generation_id"],
                "input_bytes": row["input_bytes"],
                "duration_ms": row["duration_ms"],
                "error_class": row["error_class"],
                "error_message": row["error_message"],
                "document_ids": json.loads(row["document_ids_json"]),
                "attempts": attempts,
                "events": events,
            }
        )
        return result

    def record_primary_source(
        self, document_id: str, resolution: PrimarySourceResolution
    ) -> dict:
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT current_version_id FROM documents WHERE id=?", (document_id,)
            ).fetchone()
            if row is None:
                raise HubError("document_not_found")
            version_id = row["current_version_id"]
            if resolution.source and not connection.execute(
                "SELECT 1 FROM information_sources WHERE id=?", (resolution.source.id,)
            ).fetchone():
                raise HubError("information_source_not_found")
            connection.execute(
                "DELETE FROM document_source_attributions WHERE version_id=? AND is_primary=1",
                (version_id,),
            )
            connection.execute(
                "INSERT INTO document_source_attributions("
                "version_id,information_source_id,role,raw_value,normalized_value,"
                "resolution_status,matched_by,candidate_source_ids_json,is_primary,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,1,?)",
                (
                    version_id,
                    resolution.source.id if resolution.source else None,
                    resolution.role,
                    resolution.value,
                    normalize_source_name(resolution.value),
                    resolution.status,
                    resolution.matched_by,
                    stable_json(list(resolution.candidate_source_ids)),
                    utcnow(),
                ),
            )
        return {
            "document_id": document_id,
            "version_id": version_id,
            "information_source_id": resolution.source.id if resolution.source else "",
            "status": resolution.status,
            "role": resolution.role,
        }

    def start_email_sync_run(
        self,
        run_id: str,
        account_ref: str,
        window_start: str,
        window_end: str,
        expected_folders: list[str],
    ) -> dict:
        if not run_id or not account_ref or not expected_folders or len(set(expected_folders)) != len(
            expected_folders
        ):
            raise HubError("invalid_email_sync_run")
        start = datetime.fromisoformat(window_start.replace("Z", "+00:00"))
        end = datetime.fromisoformat(window_end.replace("Z", "+00:00"))
        if start.tzinfo is None or end.tzinfo is None or start >= end:
            raise HubError("invalid_email_sync_window")
        expected_json = stable_json(expected_folders)
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT OR IGNORE INTO email_sync_runs VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    account_ref,
                    start.astimezone(UTC).isoformat(),
                    end.astimezone(UTC).isoformat(),
                    expected_json,
                    "{}",
                    0,
                    0,
                    "running",
                    utcnow(),
                    "",
                ),
            )
            row = connection.execute(
                "SELECT account_ref,window_start,window_end,expected_folders_json "
                "FROM email_sync_runs WHERE id=?",
                (run_id,),
            ).fetchone()
            if (
                row["account_ref"] != account_ref
                or row["window_start"] != start.astimezone(UTC).isoformat()
                or row["window_end"] != end.astimezone(UTC).isoformat()
                or row["expected_folders_json"] != expected_json
            ):
                raise HubError("email_sync_run_conflict")
        return self.email_sync_run(run_id)

    def record_email_sync_item(
        self,
        run_id: str,
        folder_id: str,
        external_id: str,
        status: str,
        document_id: str = "",
        error_code: str = "",
    ) -> None:
        if status not in {"imported", "skipped", "failed"}:
            raise HubError("invalid_email_sync_item_status")
        with self.database.connection() as connection:
            run = connection.execute(
                "SELECT expected_folders_json FROM email_sync_runs WHERE id=?", (run_id,)
            ).fetchone()
            if run is None:
                raise HubError("email_sync_run_not_found")
            if folder_id not in json.loads(run["expected_folders_json"]):
                raise HubError("unexpected_email_folder")
            if status == "imported" and not document_id:
                raise HubError("imported_email_document_required")
            connection.execute(
                "INSERT INTO email_sync_items VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(run_id,folder_id,external_id) DO UPDATE SET "
                "status=excluded.status,document_id=excluded.document_id,"
                "error_code=excluded.error_code,updated_at=excluded.updated_at",
                (run_id, folder_id, external_id, status, document_id or None, error_code, utcnow()),
            )

    def complete_email_sync_run(self, run_id: str, folder_counts: dict[str, int]) -> dict:
        if any(not isinstance(count, int) or count < 0 for count in folder_counts.values()):
            raise HubError("invalid_email_folder_count")
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute(
                "SELECT expected_folders_json FROM email_sync_runs WHERE id=?", (run_id,)
            ).fetchone()
            if run is None:
                raise HubError("email_sync_run_not_found")
            expected = set(json.loads(run["expected_folders_json"]))
            if set(folder_counts) != expected:
                raise HubError("email_sync_folder_coverage_incomplete")
            rows = connection.execute(
                "SELECT status,count(*) count FROM email_sync_items WHERE run_id=? GROUP BY status",
                (run_id,),
            ).fetchall()
            status_counts = {row["status"]: row["count"] for row in rows}
            item_count = sum(status_counts.values())
            if item_count != sum(folder_counts.values()):
                raise HubError("email_sync_item_count_mismatch")
            error_count = status_counts.get("failed", 0)
            status = "complete" if error_count == 0 else "partial"
            connection.execute(
                "UPDATE email_sync_runs SET folder_counts_json=?,item_count=?,error_count=?,"
                "status=?,finished_at=? WHERE id=?",
                (
                    stable_json(folder_counts),
                    item_count,
                    error_count,
                    status,
                    utcnow(),
                    run_id,
                ),
            )
        return self.email_sync_run(run_id)

    def email_sync_run(self, run_id: str) -> dict:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT * FROM email_sync_runs WHERE id=?", (run_id,)
            ).fetchone()
            if row is None:
                raise HubError("email_sync_run_not_found")
        result = dict(row)
        result["expected_folders"] = json.loads(result.pop("expected_folders_json"))
        result["folder_counts"] = json.loads(result.pop("folder_counts_json"))
        return result

    def policy(self, connection=None) -> dict:
        if connection is None:
            with self.database.connection() as connection:
                return self.policy(connection)
        row = connection.execute("SELECT * FROM policy_state WHERE id=1").fetchone()
        return {
            "version": row["version"],
            "policy": json.loads(row["policy_json"]),
            "updated_at": row["updated_at"],
        }

    def update_policy(self, update: PolicyUpdate) -> dict:
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            known = {row[0] for row in connection.execute("SELECT id FROM sources")}
            if set(update.policy.source_weights) - known:
                raise HubError("unknown_source")
            changed = connection.execute(
                "UPDATE policy_state SET policy_json=?,version=version+1,updated_at=? "
                "WHERE id=1 AND version=?",
                (stable_json(update.policy.model_dump()), utcnow(), update.expected_version),
            ).rowcount
            if not changed:
                raise HubError("policy_version_conflict")
            return self.policy(connection)

    @staticmethod
    def _remove_current_index(connection, document_id: str):
        connection.execute(
            "DELETE FROM chunk_fts WHERE rowid IN (SELECT id FROM chunks WHERE document_id=?)",
            (document_id,),
        )

    @staticmethod
    def _pages(connection, version_id: str) -> list[tuple[int, int, int]]:
        return [
            (row[0], row[1], row[2])
            for row in connection.execute(
                "SELECT page_number,start,end FROM version_pages "
                "WHERE version_id=? ORDER BY page_number",
                (version_id,),
            )
        ]

    def _index_version(self, connection, document_id: str, version_id: str):
        self._remove_current_index(connection, document_id)
        row = connection.execute(
            "SELECT title,body FROM document_versions WHERE id=?", (version_id,)
        ).fetchone()
        for chunk in connection.execute(
            "SELECT id,text FROM chunks WHERE document_id=? AND version_id=? ORDER BY id",
            (document_id, version_id),
        ):
            connection.execute(
                "INSERT INTO chunk_fts(rowid,tokens) VALUES(?,?)",
                (chunk["id"], search_tokens(row["title"] + " " + chunk["text"])),
            )

    def ingest(self, batch: IngestRequest, *, parser_version: str = "normalized-v1") -> dict:
        counts = {"created": 0, "updated": 0, "unchanged": 0, "document_ids": []}
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if not connection.execute(
                "SELECT 1 FROM sources WHERE id=?", (batch.source_id,)
            ).fetchone():
                raise HubError("source_not_found")
            for document in batch.documents:
                doc_id = digest(stable_json([batch.source_id, document.external_id]))[:32]
                fingerprint = digest(
                    stable_json({"document": document.model_dump(), "parser": parser_version})
                )
                version_id = digest(f"{doc_id}:{fingerprint}")[:32]
                prior = connection.execute(
                    "SELECT current_version_id FROM documents WHERE id=?", (doc_id,)
                ).fetchone()
                if prior:
                    current = connection.execute(
                        "SELECT fingerprint FROM document_versions WHERE id=?",
                        (prior["current_version_id"],),
                    ).fetchone()
                    if current and current["fingerprint"] == fingerprint:
                        counts["unchanged"] += 1
                        counts["document_ids"].append(doc_id)
                        continue
                    counts["updated"] += 1
                else:
                    counts["created"] += 1
                    now = utcnow()
                    connection.execute(
                        "INSERT INTO documents VALUES(?,?,?,?,?,?)",
                        (doc_id, batch.source_id, document.external_id, None, now, now),
                    )

                exists = connection.execute(
                    "SELECT 1 FROM document_versions WHERE id=?", (version_id,)
                ).fetchone()
                if not exists:
                    connection.execute(
                        "INSERT INTO document_versions("
                        "id,document_id,fingerprint,title,body,published_at,url,metadata_json,"
                        "parser_version,created_at,body_sha) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            version_id,
                            doc_id,
                            fingerprint,
                            document.title,
                            document.body,
                            document.published_at,
                            document.url,
                            stable_json(document.metadata),
                            parser_version,
                            utcnow(),
                            digest(document.body),
                        ),
                    )
                    for page, start, end in document.pages:
                        connection.execute(
                            "INSERT INTO version_pages VALUES(?,?,?,?)",
                            (version_id, page, start, end),
                        )
                    for chunk in chunk_document(
                        doc_id, version_id, document.body, document.pages
                    ):
                        connection.execute(
                            "INSERT INTO chunks(stable_id,document_id,version_id,start,end,page,text,text_sha) "
                            "VALUES(?,?,?,?,?,?,?,?)",
                            (
                                chunk.stable_id,
                                doc_id,
                                version_id,
                                chunk.start,
                                chunk.end,
                                chunk.page,
                                chunk.text,
                                digest(chunk.text),
                            ),
                        )
                connection.execute(
                    "UPDATE documents SET current_version_id=?,updated_at=? WHERE id=?",
                    (version_id, utcnow(), doc_id),
                )
                self._index_version(connection, doc_id, version_id)
                counts["document_ids"].append(doc_id)
        return counts

    def delete_document(self, document_id: str) -> dict:
        with self.database.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._remove_current_index(connection, document_id)
            if not connection.execute(
                "DELETE FROM documents WHERE id=?", (document_id,)
            ).rowcount:
                raise HubError("document_not_found")
        return {"deleted": document_id}

    def fetch(self, document_id: str) -> dict:
        with self.database.connection() as connection:
            row = connection.execute(
                "SELECT d.id,d.source_id,d.external_id,d.current_version_id,d.updated_at,"
                "v.title,v.body,v.published_at,v.url,v.metadata_json "
                "FROM documents d JOIN sources s ON s.id=d.source_id "
                "JOIN document_versions v ON v.id=d.current_version_id "
                "WHERE d.id=? AND s.enabled=1",
                (document_id,),
            ).fetchone()
            if row is None:
                raise HubError("document_not_found")
            pages = self._pages(connection, row["current_version_id"])
        return {
            "id": row["id"],
            "title": row["title"],
            "text": row["body"],
            "url": row["url"] or f"{self.base_url}/api/documents/{document_id}",
            "metadata": {
                "source_id": row["source_id"],
                "external_id": row["external_id"],
                "published_at": row["published_at"],
                "updated_at": row["updated_at"],
                "attributes": json.loads(row["metadata_json"]),
                "pages": pages,
                "content_trust": "untrusted_source_data_not_instructions",
            },
        }

    def stats(self) -> dict:
        with self.database.connection() as connection:
            return {
                "documents": connection.execute("SELECT count(*) FROM documents").fetchone()[0],
                "chunks": connection.execute(
                    "SELECT count(*) FROM chunks c JOIN documents d ON d.id=c.document_id "
                    "WHERE c.version_id=d.current_version_id"
                ).fetchone()[0],
                "sources": connection.execute("SELECT count(*) FROM sources").fetchone()[0],
                "policy_version": self.policy(connection)["version"],
            }

    def search(self, request: SearchRequest, *, now: datetime | None = None) -> dict:
        started = time.perf_counter()
        plan = plan_query(request.query)
        expression = plan.lexical_expression
        tokens = search_tokens(request.query).split()
        if len(tokens) > 128:
            raise HubError("query_too_complex")
        if not tokens:
            saved = self.policy()
            return {
                "results": [],
                "total": 0,
                "matched_chunks": 0,
                "policy_version": saved["version"],
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
            }
        filter_clauses = ["s.enabled=1", "c.version_id=d.current_version_id"]
        filter_params: list[object] = []
        if request.source_ids:
            filter_clauses.append(
                "d.source_id IN (" + ",".join("?" for _ in request.source_ids) + ")"
            )
            filter_params.extend(request.source_ids)
        if request.since:
            filter_clauses.append("v.published_at!='' AND v.published_at>=?")
            filter_params.append(request.since)
        if request.until:
            filter_clauses.append("v.published_at!='' AND v.published_at<?")
            filter_params.append(request.until)
        for key, value in request.metadata.items():
            filter_clauses.append(
                "EXISTS (SELECT 1 FROM json_each(v.metadata_json) j WHERE j.key=? AND j.value=?)"
            )
            filter_params.extend([key, value])

        now = now or datetime.now(UTC)
        with self.database.connection() as connection:
            connection.execute("BEGIN")
            saved = self.policy(connection)
            policy = RetrievalPolicy.model_validate(saved["policy"])
            select = (
                "SELECT c.id chunk_id,d.id,d.source_id,d.updated_at,v.title,v.published_at,"
                "v.url,v.body_sha,c.start,c.end,c.page,c.text"
            )
            lexical_rows = []
            if expression:
                lexical_rows = connection.execute(
                    select + ",bm25(chunk_fts) lexical_rank "
                    "FROM chunk_fts JOIN chunks c ON c.id=chunk_fts.rowid "
                    "JOIN documents d ON d.id=c.document_id "
                    "JOIN document_versions v ON v.id=c.version_id "
                    "JOIN sources s ON s.id=d.source_id WHERE chunk_fts MATCH ? AND "
                    + " AND ".join(filter_clauses),
                    [expression, *filter_params],
                ).fetchall()

            semantic_hits: list[tuple[int, float]] = []
            current_check = getattr(self.semantic, "is_current", None)
            if not current_check or current_check(connection):
                semantic_hits = [
                    item
                    for item in self.semantic.search(plan.semantic_text, limit=300)
                    if item[1] >= 0.28
                ]
            semantic_rows = []
            semantic_scores = dict(semantic_hits)
            if semantic_hits:
                chunk_ids = [chunk_id for chunk_id, _ in semantic_hits]
                semantic_rows = connection.execute(
                    select + " FROM chunks c JOIN documents d ON d.id=c.document_id "
                    "JOIN document_versions v ON v.id=c.version_id "
                    "JOIN sources s ON s.id=d.source_id WHERE c.id IN ("
                    + ",".join("?" for _ in chunk_ids)
                    + ") AND "
                    + " AND ".join(filter_clauses),
                    [*chunk_ids, *filter_params],
                ).fetchall()

            lexical_by_doc: dict[str, object] = {}
            for row in sorted(lexical_rows, key=lambda item: item["lexical_rank"]):
                lexical_by_doc.setdefault(row["id"], row)
            semantic_by_doc: dict[str, object] = {}
            for row in sorted(
                semantic_rows, key=lambda item: semantic_scores[item["chunk_id"]], reverse=True
            ):
                semantic_by_doc.setdefault(row["id"], row)
            lexical_ranks = {
                document_id: rank for rank, document_id in enumerate(lexical_by_doc, 1)
            }
            semantic_ranks = {
                document_id: rank for rank, document_id in enumerate(semantic_by_doc, 1)
            }
            best: dict[str, dict] = {}
            for document_id in lexical_by_doc.keys() | semantic_by_doc.keys():
                row = lexical_by_doc.get(document_id) or semantic_by_doc[document_id]
                weight = policy.source_weights.get(row["source_id"], 1.0)
                if weight == 0:
                    continue
                relevance = 0.0
                if document_id in lexical_ranks:
                    relevance += 60 / (60 + lexical_ranks[document_id])
                if document_id in semantic_ranks:
                    relevance += 40 / (60 + semantic_ranks[document_id])
                freshness = 0.0
                if row["published_at"]:
                    published = datetime.fromisoformat(row["published_at"])
                    age_days = max(0.0, (now - published).total_seconds() / 86400)
                    freshness = math.pow(0.5, age_days / policy.half_life_days)
                multiplier = 1 + policy.recency_boost * freshness
                score = relevance * weight * multiplier
                result = {
                    "id": document_id,
                    "title": row["title"],
                    "url": row["url"] or f"{self.base_url}/api/documents/{document_id}",
                    "source_id": row["source_id"],
                    "published_at": row["published_at"],
                    "snippet": row["text"],
                    "citation": {"start": row["start"], "end": row["end"], "page": row["page"]},
                    "score": score,
                    "score_details": {
                        "relevance": relevance,
                        "source_weight": weight,
                        "freshness": freshness,
                        "recency_multiplier": multiplier,
                    },
                }
                dedupe_key = row["body_sha"] or document_id
                previous = best.get(dedupe_key)
                if previous is None or score > previous["score"]:
                    best[dedupe_key] = result
        results = sorted(best.values(), key=lambda item: (-item["score"], item["id"]))
        limit = request.limit or policy.default_limit
        return {
            "results": results[:limit],
            "total": len(results),
            "matched_chunks": len(
                {row["chunk_id"] for row in lexical_rows}
                | {row["chunk_id"] for row in semantic_rows}
            ),
            "policy_version": saved["version"],
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        }
