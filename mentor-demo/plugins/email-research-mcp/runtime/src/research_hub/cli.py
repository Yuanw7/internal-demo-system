from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from .models import (
    DocumentInput,
    IngestRequest,
    PolicyUpdate,
    RetrievalPolicy,
    SearchRequest,
    SourceDefinition,
)
from .parsing import PARSER_VERSION, documents_from_path, parse_bytes
from .runtime import credentials, initialize
from .service import HubError, RetrievalHub
from .source_ranking import (
    DEFAULT_SOURCE_RANKING_V1_PATH,
    SourceCandidate,
    load_source_ranking_catalog,
    source_candidates_from_metadata,
)


def ingest_in_batches(hub: RetrievalHub, source_id: str, documents: list[DocumentInput]) -> dict:
    totals = {"created": 0, "updated": 0, "unchanged": 0, "document_ids": []}
    batch: list[DocumentInput] = []
    body_chars = 0

    def flush() -> None:
        nonlocal batch, body_chars
        if not batch:
            return
        result = hub.ingest(
            IngestRequest(source_id=source_id, documents=batch),
            parser_version=PARSER_VERSION,
        )
        for key in ("created", "updated", "unchanged"):
            totals[key] += result[key]
        totals["document_ids"].extend(result["document_ids"])
        batch = []
        body_chars = 0

    for document in documents:
        if batch and (len(batch) >= 100 or body_chars + len(document.body) > 2_000_000):
            flush()
        batch.append(document)
        body_chars += len(document.body)
    flush()
    return totals


def seed_demo(hub: RetrievalHub) -> dict:
    fixtures = (
        (
            "demo_research",
            "虚构样例 · 研究纪要",
            "2026-09-01T00:00:00Z",
            "【虚构测试数据】分析师认为算力需求增长将推动芯片采购，但资本开支节奏仍存在不确定性。",
        ),
        (
            "demo_filings",
            "虚构样例 · 公司公告",
            "2026-08-01T00:00:00Z",
            "【虚构测试数据】公司披露数据中心投资计划，并提示供应链和需求波动风险。",
        ),
    )
    for source_id, name, published, body in fixtures:
        hub.upsert_source(SourceDefinition(id=source_id, name=name, kind="demo"))
        hub.ingest(
            IngestRequest(
                source_id=source_id,
                documents=[
                    DocumentInput(
                        external_id="demo-001",
                        title=f"{name}：算力投资观点",
                        body=body,
                        published_at=published,
                        metadata={"company": "虚构公司", "sector": "科技", "report_type": "demo"},
                    )
                ],
            ),
            parser_version="fixture-v1",
        )
    return hub.stats()


def seed_source_ranking_demo(hub: RetrievalHub) -> dict:
    """Create a fictional, repeatable V0 corpus without touching real accounts or content."""
    catalog = load_source_ranking_catalog()
    for source in catalog.sources.values():
        hub.upsert_source(SourceDefinition(id=source.id, name=source.display_name, kind="demo"))

    fixtures = (
        (
            "fixture_orion_lee",
            "priority-evidence",
            "虚构分析师：芯片需求",
            "【虚构测试数据】芯片需求增长，资本开支仍需验证。",
        ),
        (
            "fixture_public_news",
            "priority-evidence",
            "虚构新闻：芯片需求",
            "【虚构测试数据】芯片需求增长，库存周期仍需验证。",
        ),
    )
    totals = {"created": 0, "updated": 0, "unchanged": 0}
    for source_id, external_id, title, body in fixtures:
        result = hub.ingest(
            IngestRequest(
                source_id=source_id,
                documents=[
                    DocumentInput(
                        external_id=external_id,
                        title=title,
                        body=body,
                        metadata={
                            "fixture": "information-source-ranking-v0",
                            "content_type": "fictional_research",
                        },
                    )
                ],
            ),
            parser_version="source-ranking-fixture-v0",
        )
        for key in totals:
            totals[key] += result[key]

    current = hub.policy()
    policy = RetrievalPolicy.model_validate(current["policy"])
    desired = policy.model_copy(
        update={"source_weights": policy.source_weights | catalog.policy_weights()}
    )
    if desired.model_dump() != policy.model_dump():
        current = hub.update_policy(
            PolicyUpdate(expected_version=current["version"], policy=desired)
        )
    primary = catalog.resolve_primary([SourceCandidate("analyst", "O. Lee")])
    return {
        "catalog_version": catalog.version,
        "primary_source": primary.source.id if primary.source else "",
        "ingest": totals,
        "policy_version": current["version"],
        "stats": hub.stats(),
        "real_content_processed": False,
    }


V1_EMAIL_FOLDERS = ["inbox", "inbox_sellside", "inbox_third_party"]


def seed_source_ranking_v1_demo(hub: RetrievalHub) -> dict:
    """Persist a fictional email batch, source aliases, and primary attributions."""
    catalog = load_source_ranking_catalog(DEFAULT_SOURCE_RANKING_V1_PATH)
    catalog_status = hub.sync_information_source_catalog(catalog, retrieval_kind="demo")
    run_id = "fixture-email-sync-2026-09-28-v1"
    hub.start_email_sync_run(
        run_id,
        "fixture-account",
        "2026-09-28T00:00:00+08:00",
        "2026-09-29T00:00:00+08:00",
        V1_EMAIL_FOLDERS,
    )

    parsed_email = parse_bytes(
        "fixture-email.eml",
        (
            "From: Orion Lee <orion.lee@fictional.example>\n"
            "To: research@fictional.example\n"
            "Date: Mon, 28 Sep 2026 08:30:00 +0800\n"
            "Message-ID: <fixture-email-001@fictional.example>\n"
            "Subject: Fictional chip demand update\n"
            "Content-Type: text/plain; charset=utf-8\n\n"
            "【虚构测试数据】芯片需求增长，AI基础设施资本开支仍需验证。"
        ).encode("utf-8"),
    )[0]
    email_metadata = parsed_email.metadata | {
        "ingestion_channel": "fixture_outlook",
        "email_folder": "inbox_sellside",
        "content_type": "fictional_email",
    }
    documents = [
        (
            "inbox_sellside",
            "fixture-email-001",
            DocumentInput(
                external_id="fixture-email-001",
                title=parsed_email.title,
                body=parsed_email.body,
                published_at=parsed_email.published_at,
                metadata=email_metadata,
            ),
        ),
        (
            "inbox",
            "fixture-json-001",
            DocumentInput(
                external_id="fixture-json-001",
                title="Fictional institution chip demand note",
                body="【虚构测试数据】芯片需求增长，但库存与交付节奏仍存在分歧。",
                published_at="2026-09-28T01:00:00Z",
                metadata={
                    "institution": "Northstar Research",
                    "ingestion_channel": "fixture_json",
                    "email_folder": "inbox",
                    "content_type": "fictional_email",
                },
            ),
        ),
    ]

    totals = {"created": 0, "updated": 0, "unchanged": 0}
    attributions = []
    for folder_id, external_id, document in documents:
        resolution = catalog.resolve_primary(source_candidates_from_metadata(document.metadata))
        if not resolution.source:
            raise HubError("fixture_primary_source_not_resolved")
        result = hub.ingest(
            IngestRequest(source_id=resolution.source.id, documents=[document]),
            parser_version="email-source-ranking-fixture-v1",
        )
        for key in totals:
            totals[key] += result[key]
        document_id = result["document_ids"][0]
        attributions.append(hub.record_primary_source(document_id, resolution))
        hub.record_email_sync_item(
            run_id,
            folder_id,
            external_id,
            "imported",
            document_id=document_id,
        )

    sync = hub.complete_email_sync_run(
        run_id,
        {"inbox": 1, "inbox_sellside": 1, "inbox_third_party": 0},
    )
    current = hub.policy()
    policy = RetrievalPolicy.model_validate(current["policy"])
    desired = policy.model_copy(
        update={"source_weights": policy.source_weights | catalog.policy_weights()}
    )
    if desired.model_dump() != policy.model_dump():
        current = hub.update_policy(
            PolicyUpdate(expected_version=current["version"], policy=desired)
        )
    return {
        "version": "information-source-ranking-v1",
        "catalog": catalog_status,
        "ingest": totals,
        "attributions": attributions,
        "sync": sync,
        "information_sources": hub.information_sources(),
        "policy_version": current["version"],
        "stats": hub.stats(),
        "real_content_processed": False,
    }


def run(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Local internal research Retrieval Hub")
    parser.add_argument("--data-dir", type=Path, default=Path("data/hub"))
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--credentials", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Create local credentials and a Codex MCP config snippet")
    commands.add_parser("demo", help="Import clearly labelled fictional fixtures")
    commands.add_parser(
        "source-ranking-demo",
        help="Import fictional Priority 1-4 source-ranking V0 fixtures",
    )
    commands.add_parser(
        "source-ranking-v1-demo",
        help="Import a fictional email batch with persistent source attribution",
    )
    commands.add_parser("status")
    semantic_build = commands.add_parser("semantic-build", help="Build the local dense-vector index")
    semantic_build.add_argument("--batch-size", type=int, default=64)
    commands.add_parser("semantic-status", help="Show dense-vector index metadata")
    source = commands.add_parser("source")
    source.add_argument("--id", required=True)
    source.add_argument("--name", required=True)
    source.add_argument("--kind", default="local", choices=["local", "api", "sharepoint", "database", "demo"])
    source.add_argument("--disabled", action="store_true")
    ingest = commands.add_parser("ingest")
    ingest.add_argument("path", type=Path)
    ingest.add_argument("--source-id", required=True)
    ingest.add_argument("--source-name", required=True)
    search = commands.add_parser("search")
    search.add_argument("query")
    serve = commands.add_parser("serve")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--cors-origin", action="append", default=[])
    commands.add_parser("stdio", help="Run the read-only MCP server over stdio")
    export = commands.add_parser("export-openapi")
    export.add_argument("output", type=Path)
    args = parser.parse_args(argv)

    port = getattr(args, "port", 8765)
    if not 1 <= port <= 65535:
        raise HubError("invalid_port")
    base_url = args.base_url or f"http://127.0.0.1:{port}"
    credential_path = args.credentials or args.data_dir / "access.local.json"
    hub = RetrievalHub(args.data_dir, base_url)

    if args.command == "init":
        result = initialize(args.data_dir, credential_path, Path.cwd())
    elif args.command == "demo":
        result = seed_demo(hub)
    elif args.command == "source-ranking-demo":
        result = seed_source_ranking_demo(hub)
    elif args.command == "source-ranking-v1-demo":
        result = seed_source_ranking_v1_demo(hub)
    elif args.command == "status":
        result = hub.stats()
    elif args.command == "semantic-build":
        if not 1 <= args.batch_size <= 1024:
            raise HubError("invalid_batch_size")
        result = hub.semantic.build(hub.database, batch_size=args.batch_size)
    elif args.command == "semantic-status":
        result = {"available": hub.semantic.available(), "metadata": hub.semantic.metadata()}
    elif args.command == "source":
        result = hub.upsert_source(
            SourceDefinition(
                id=args.id,
                name=args.name,
                kind=args.kind,
                enabled=not args.disabled,
            )
        )
    elif args.command == "ingest":
        if args.source_id not in {item["id"] for item in hub.sources()}:
            hub.upsert_source(SourceDefinition(id=args.source_id, name=args.source_name, kind="local"))
        documents, errors = documents_from_path(args.path)
        if not documents:
            result = {"created": 0, "updated": 0, "unchanged": 0, "document_ids": [], "errors": errors}
        else:
            result = ingest_in_batches(hub, args.source_id, documents)
            result["errors"] = errors
    elif args.command == "search":
        result = hub.search(SearchRequest(query=args.query))
    elif args.command == "stdio":
        from .mcp_server import create_mcp

        create_mcp(hub).run(transport="stdio")
        return 0
    else:
        from .api import create_app

        if args.command == "export-openapi":
            app = create_app(hub, "schema-read-" + "x" * 32, "schema-admin-" + "x" * 32)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2), encoding="utf-8")
            return 0
        import uvicorn

        read_token, admin_token = credentials(credential_path)
        app = create_app(hub, read_token, admin_token, args.cors_origin)
        uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)
        return 0
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if result.get("errors") else 0


def main(argv=None) -> int:
    try:
        return run(argv)
    except KeyboardInterrupt:
        return 130
    except ValidationError as exc:
        error = {"code": "validation_error", "fields": [".".join(map(str, item["loc"])) for item in exc.errors()]}
    except (HubError, RuntimeError, ValueError) as exc:
        error = {"code": str(exc)}
    except OSError:
        error = {"code": "file_or_runtime_error"}
    print(json.dumps({"error": error}, ensure_ascii=False), file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
