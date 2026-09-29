from __future__ import annotations

import json
import math
import time
from datetime import UTC, datetime
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
