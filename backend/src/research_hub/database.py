from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .models import RetrievalPolicy
from .util import digest, stable_json, utcnow


MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL
    );
    CREATE TABLE sources (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        kind TEXT NOT NULL,
        enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE documents (
        id TEXT PRIMARY KEY,
        source_id TEXT NOT NULL REFERENCES sources(id),
        external_id TEXT NOT NULL,
        current_version_id TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(source_id, external_id)
    );
    CREATE TABLE document_versions (
        id TEXT PRIMARY KEY,
        document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        fingerprint TEXT NOT NULL,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        published_at TEXT NOT NULL,
        url TEXT NOT NULL,
        metadata_json TEXT NOT NULL,
        parser_version TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(document_id, fingerprint)
    );
    CREATE TABLE version_pages (
        version_id TEXT NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
        page_number INTEGER NOT NULL,
        start INTEGER NOT NULL,
        end INTEGER NOT NULL,
        PRIMARY KEY(version_id, page_number)
    );
    CREATE TABLE chunks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        stable_id TEXT NOT NULL UNIQUE,
        document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        version_id TEXT NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
        start INTEGER NOT NULL,
        end INTEGER NOT NULL,
        page INTEGER,
        text TEXT NOT NULL,
        text_sha TEXT NOT NULL
    );
    CREATE INDEX chunk_document_version ON chunks(document_id, version_id);
    CREATE INDEX document_source ON documents(source_id);
    CREATE INDEX version_published ON document_versions(published_at);
    CREATE VIRTUAL TABLE chunk_fts USING fts5(tokens);
    CREATE TABLE policy_state (
        id INTEGER PRIMARY KEY CHECK(id=1),
        version INTEGER NOT NULL,
        policy_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    """
    ALTER TABLE document_versions ADD COLUMN body_sha TEXT NOT NULL DEFAULT '';
    CREATE INDEX version_body_sha ON document_versions(body_sha);
    """,
    """
    CREATE TABLE information_sources (
        id TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        source_type TEXT NOT NULL,
        priority_tier INTEGER NOT NULL CHECK(priority_tier BETWEEN 1 AND 4),
        enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
        catalog_version TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE information_source_aliases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_id TEXT NOT NULL REFERENCES information_sources(id) ON DELETE CASCADE,
        alias TEXT NOT NULL,
        normalized_alias TEXT NOT NULL,
        alias_type TEXT NOT NULL CHECK(alias_type IN ('canonical','explicit')),
        created_at TEXT NOT NULL,
        UNIQUE(source_id,normalized_alias)
    );
    CREATE INDEX information_source_alias_lookup
        ON information_source_aliases(normalized_alias);
    CREATE TABLE document_source_attributions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        version_id TEXT NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
        information_source_id TEXT REFERENCES information_sources(id),
        role TEXT NOT NULL,
        raw_value TEXT NOT NULL,
        normalized_value TEXT NOT NULL,
        resolution_status TEXT NOT NULL
            CHECK(resolution_status IN ('matched','ambiguous','unmatched')),
        matched_by TEXT NOT NULL,
        candidate_source_ids_json TEXT NOT NULL,
        is_primary INTEGER NOT NULL CHECK(is_primary IN (0,1)),
        created_at TEXT NOT NULL,
        UNIQUE(version_id,role,normalized_value,is_primary)
    );
    CREATE INDEX attribution_version ON document_source_attributions(version_id);
    CREATE INDEX attribution_information_source
        ON document_source_attributions(information_source_id);
    CREATE TABLE email_sync_runs (
        id TEXT PRIMARY KEY,
        account_ref TEXT NOT NULL,
        window_start TEXT NOT NULL,
        window_end TEXT NOT NULL,
        expected_folders_json TEXT NOT NULL,
        folder_counts_json TEXT NOT NULL,
        item_count INTEGER NOT NULL,
        error_count INTEGER NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('running','complete','partial','failed')),
        started_at TEXT NOT NULL,
        finished_at TEXT NOT NULL
    );
    CREATE TABLE email_sync_items (
        run_id TEXT NOT NULL REFERENCES email_sync_runs(id) ON DELETE CASCADE,
        folder_id TEXT NOT NULL,
        external_id TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('imported','skipped','failed')),
        document_id TEXT REFERENCES documents(id),
        error_code TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY(run_id,folder_id,external_id)
    );
    CREATE INDEX email_sync_item_document ON email_sync_items(document_id);
    """,
    """
    CREATE TABLE ingestion_connectors (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        kind TEXT NOT NULL CHECK(kind IN ('local_folder','outlook')),
        enabled INTEGER NOT NULL CHECK(enabled IN (0,1)),
        config_json TEXT NOT NULL,
        semantic_required INTEGER NOT NULL CHECK(semantic_required IN (0,1)),
        processing_priority INTEGER NOT NULL DEFAULT 0,
        state_version INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE ingestion_checkpoints (
        connector_id TEXT PRIMARY KEY REFERENCES ingestion_connectors(id) ON DELETE CASCADE,
        cursor_kind TEXT NOT NULL,
        cursor_value TEXT NOT NULL,
        last_scan_started_at TEXT NOT NULL,
        last_scan_succeeded_at TEXT NOT NULL,
        last_error_code TEXT NOT NULL,
        state_version INTEGER NOT NULL DEFAULT 1,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE ingestion_batches (
        id TEXT PRIMARY KEY,
        connector_id TEXT NOT NULL REFERENCES ingestion_connectors(id),
        trigger_kind TEXT NOT NULL CHECK(trigger_kind IN ('poll','manual','reconciliation','outlook_delta')),
        status TEXT NOT NULL CHECK(status IN ('pending','processing','processed','failed','retrying')),
        discovered_count INTEGER NOT NULL DEFAULT 0,
        processed_count INTEGER NOT NULL DEFAULT 0,
        failed_count INTEGER NOT NULL DEFAULT 0,
        retrying_count INTEGER NOT NULL DEFAULT 0,
        unchanged_count INTEGER NOT NULL DEFAULT 0,
        state_version INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE TABLE ingestion_items (
        id TEXT PRIMARY KEY,
        connector_id TEXT NOT NULL REFERENCES ingestion_connectors(id),
        external_id TEXT NOT NULL,
        display_name TEXT NOT NULL,
        source_locator TEXT NOT NULL,
        content_fingerprint TEXT NOT NULL,
        pipeline_version TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('pending','processing','processed','failed','retrying')),
        pipeline_stage TEXT NOT NULL CHECK(pipeline_stage IN ('discovered','stability_check','fetch','parse','persist','fts_index','vectorize','publish')),
        outcome TEXT NOT NULL,
        semantic_required INTEGER NOT NULL CHECK(semantic_required IN (0,1)),
        processing_priority INTEGER NOT NULL DEFAULT 0,
        attempt_count INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL,
        eligible_at TEXT NOT NULL,
        next_attempt_at TEXT,
        lease_owner TEXT,
        lease_expires_at TEXT,
        discovered_at TEXT NOT NULL,
        started_at TEXT,
        searchable_at TEXT,
        finished_at TEXT,
        updated_at TEXT NOT NULL,
        document_ids_json TEXT NOT NULL,
        semantic_generation_id TEXT,
        input_bytes INTEGER NOT NULL DEFAULT 0,
        duration_ms INTEGER,
        error_class TEXT NOT NULL,
        error_code TEXT NOT NULL,
        error_message TEXT NOT NULL,
        state_version INTEGER NOT NULL DEFAULT 1,
        UNIQUE(connector_id,idempotency_key)
    );
    CREATE TABLE ingestion_batch_items (
        batch_id TEXT NOT NULL REFERENCES ingestion_batches(id) ON DELETE CASCADE,
        item_id TEXT NOT NULL REFERENCES ingestion_items(id) ON DELETE CASCADE,
        discovery_outcome TEXT NOT NULL CHECK(discovery_outcome IN ('new','changed','already_known')),
        PRIMARY KEY(batch_id,item_id)
    );
    CREATE TABLE ingestion_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id TEXT NOT NULL REFERENCES ingestion_items(id) ON DELETE CASCADE,
        attempt_number INTEGER NOT NULL,
        worker_id TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        outcome TEXT NOT NULL,
        error_class TEXT NOT NULL,
        error_code TEXT NOT NULL,
        duration_ms INTEGER,
        UNIQUE(item_id,attempt_number)
    );
    CREATE TABLE ingestion_status_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id TEXT NOT NULL REFERENCES ingestion_items(id) ON DELETE CASCADE,
        from_status TEXT NOT NULL,
        to_status TEXT NOT NULL,
        pipeline_stage TEXT NOT NULL,
        state_version INTEGER NOT NULL,
        actor_type TEXT NOT NULL,
        actor_id TEXT NOT NULL,
        reason TEXT NOT NULL,
        occurred_at TEXT NOT NULL
    );
    CREATE TABLE ingestion_dead_letters (
        item_id TEXT PRIMARY KEY REFERENCES ingestion_items(id) ON DELETE CASCADE,
        terminal_reason TEXT NOT NULL,
        failed_stage TEXT NOT NULL,
        last_attempt_number INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        resolved_at TEXT,
        resolution_note TEXT NOT NULL
    );
    CREATE INDEX ingestion_item_queue ON ingestion_items(status,eligible_at,next_attempt_at,processing_priority);
    CREATE INDEX ingestion_item_connector_status ON ingestion_items(connector_id,status,discovered_at);
    CREATE INDEX ingestion_item_finished ON ingestion_items(finished_at,status);
    CREATE INDEX ingestion_item_lease ON ingestion_items(status,lease_expires_at);
    CREATE INDEX ingestion_item_error ON ingestion_items(error_code,finished_at);
    CREATE INDEX ingestion_batch_connector_time ON ingestion_batches(connector_id,created_at);
    CREATE INDEX ingestion_attempt_item ON ingestion_attempts(item_id,attempt_number);
    CREATE INDEX ingestion_event_item ON ingestion_status_events(item_id,id);
    """,
    """
    CREATE TABLE ingestion_source_objects (
        connector_id TEXT NOT NULL REFERENCES ingestion_connectors(id) ON DELETE CASCADE,
        external_id TEXT NOT NULL,
        size_bytes INTEGER NOT NULL,
        mtime_ns INTEGER NOT NULL,
        content_fingerprint TEXT NOT NULL,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        stable_since TEXT NOT NULL,
        last_enqueued_fingerprint TEXT NOT NULL,
        deleted_at TEXT,
        PRIMARY KEY(connector_id,external_id)
    );
    CREATE TABLE ingestion_worker_heartbeats (
        worker_id TEXT PRIMARY KEY,
        connector_id TEXT NOT NULL REFERENCES ingestion_connectors(id) ON DELETE CASCADE,
        current_item_id TEXT REFERENCES ingestion_items(id) ON DELETE SET NULL,
        state TEXT NOT NULL CHECK(state IN ('idle','processing','backpressured','stopped')),
        last_seen_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    ALTER TABLE ingestion_items ADD COLUMN parent_item_id TEXT REFERENCES ingestion_items(id);
    ALTER TABLE ingestion_items ADD COLUMN item_kind TEXT NOT NULL DEFAULT 'document';
    ALTER TABLE ingestion_items ADD COLUMN required_for_parent INTEGER NOT NULL DEFAULT 0
        CHECK(required_for_parent IN (0,1));
    CREATE INDEX ingestion_source_object_seen
        ON ingestion_source_objects(connector_id,last_seen_at,deleted_at);
    CREATE INDEX ingestion_item_parent ON ingestion_items(parent_item_id,status);
    CREATE INDEX ingestion_worker_connector ON ingestion_worker_heartbeats(connector_id,last_seen_at);
    """,
)


class Database:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "hub.sqlite3"
        self.migrate()

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.path, timeout=20)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=20000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def migrate(self):
        with sqlite3.connect(self.path, timeout=20) as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")
            has_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
            ).fetchone()
            current = (
                connection.execute("SELECT max(version) FROM schema_migrations").fetchone()[0] or 0
                if has_table
                else 0
            )
            if current > len(MIGRATIONS):
                raise RuntimeError("unsupported_database_version")
            for version, sql in enumerate(MIGRATIONS[current:], current + 1):
                connection.executescript(sql)
                if version == 2:
                    rows = connection.execute(
                        "SELECT id,body FROM document_versions WHERE body_sha=''"
                    ).fetchall()
                    connection.executemany(
                        "UPDATE document_versions SET body_sha=? WHERE id=?",
                        [(digest(body), version_id) for version_id, body in rows],
                    )
                connection.execute(
                    "INSERT INTO schema_migrations(version,applied_at) VALUES(?,?)",
                    (version, utcnow()),
                )
            connection.execute(
                "INSERT OR IGNORE INTO policy_state VALUES(1,1,?,?)",
                (stable_json(RetrievalPolicy().model_dump()), utcnow()),
            )
