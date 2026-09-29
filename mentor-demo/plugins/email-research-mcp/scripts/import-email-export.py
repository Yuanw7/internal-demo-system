#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from research_hub.models import DocumentInput, IngestRequest, PolicyUpdate, RetrievalPolicy
from research_hub.parsing import PARSER_VERSION, parse_bytes
from research_hub.service import HubError, RetrievalHub
from research_hub.source_ranking import (
    PrimarySourceResolution,
    SourceCandidate,
    load_source_ranking_catalog,
    source_candidates_from_metadata,
)
from research_hub.util import digest, stable_json


FOLDERS = {
    "inbox": Path("Inbox"),
    "inbox_sellside": Path("Inbox") / "Anatole Must Read Sellside",
    "inbox_third_party": Path("Inbox") / "Anatole 3 Party Tracking",
}
SUPPORTED = {".eml", ".json", ".jsonl"}


def files_in(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(item for item in folder.iterdir() if item.is_file() and item.suffix.lower() in SUPPORTED)


def unresolved(
    status: str,
    candidates: tuple[SourceCandidate, ...],
    resolution: PrimarySourceResolution,
    fallback_value: str,
) -> PrimarySourceResolution:
    candidate = candidates[0] if candidates else SourceCandidate("email_sender", fallback_value)
    return PrimarySourceResolution(
        status=status,
        source=None,
        role=candidate.role,
        value=candidate.value,
        matched_by="",
        candidate_source_ids=resolution.candidate_source_ids,
        checks=resolution.checks,
    )


def run(args: argparse.Namespace) -> dict:
    input_dir = args.input_dir.resolve()
    if not input_dir.is_dir():
        raise HubError("input_directory_not_found")

    catalog = load_source_ranking_catalog(args.source_config.resolve())
    if args.fallback_source_id not in catalog.sources:
        raise HubError("fallback_source_not_in_catalog")

    hub = RetrievalHub(args.data_dir.resolve())
    catalog_status = hub.sync_information_source_catalog(catalog, retrieval_kind="local")
    file_groups = {
        folder_id: files_in(input_dir / relative)
        for folder_id, relative in FOLDERS.items()
    }
    signature = [
        args.account_ref,
        args.window_start,
        args.window_end,
        [
            f"{folder_id}:{path.relative_to(input_dir).as_posix()}"
            for folder_id, paths in file_groups.items()
            for path in paths
        ],
    ]
    run_id = "local-email-export-" + digest(stable_json(signature))[:16]
    hub.start_email_sync_run(
        run_id,
        args.account_ref,
        args.window_start,
        args.window_end,
        list(FOLDERS),
    )

    folder_counts = {folder_id: 0 for folder_id in FOLDERS}
    ingest = {"created": 0, "updated": 0, "unchanged": 0}
    attribution_counts = {"matched": 0, "ambiguous": 0, "unmatched": 0}
    errors: list[dict[str, str]] = []

    for folder_id, paths in file_groups.items():
        for path in paths:
            relative = path.relative_to(input_dir).as_posix()
            try:
                parsed_documents = parse_bytes(path.name, path.read_bytes())
            except (OSError, ValueError) as exc:
                folder_counts[folder_id] += 1
                code = str(exc) or "parse_failed"
                hub.record_email_sync_item(run_id, folder_id, relative, "failed", error_code=code)
                errors.append({"file": relative, "error": code})
                continue

            for index, parsed in enumerate(parsed_documents):
                external_id = f"{relative}#{index}"
                folder_counts[folder_id] += 1
                metadata = dict(parsed.metadata)
                metadata.setdefault("email_received_at", parsed.published_at)
                metadata.setdefault("report_published_at", parsed.published_at)
                metadata.setdefault(
                    "attachment_status",
                    "not_parsed" if "email_attachment_not_parsed" in parsed.warnings else "not_applicable",
                )
                metadata.update(
                    {
                        "content_type": "mentor_email",
                        "email_folder": folder_id,
                        "file_name": path.name,
                        "ingestion_channel": "local_email_export",
                        "parser_version": PARSER_VERSION,
                        "parser_warnings": ";".join(parsed.warnings)[:1000],
                    }
                )
                document = DocumentInput(
                    external_id=external_id,
                    title=parsed.title,
                    body=parsed.body,
                    published_at=parsed.published_at,
                    url=parsed.url,
                    metadata=metadata,
                    pages=parsed.pages,
                )
                candidates = source_candidates_from_metadata(metadata)
                resolution = catalog.resolve_primary(candidates)
                source_id = (
                    resolution.source.id if resolution.source else args.fallback_source_id
                )
                if not resolution.source:
                    resolution = unresolved(resolution.status, candidates, resolution, relative)

                result = hub.ingest(
                    IngestRequest(source_id=source_id, documents=[document]),
                    parser_version="mentor-email-export-v1",
                )
                for key in ingest:
                    ingest[key] += result[key]
                document_id = result["document_ids"][0]
                hub.record_primary_source(document_id, resolution)
                attribution_counts[resolution.status] += 1
                hub.record_email_sync_item(
                    run_id,
                    folder_id,
                    external_id,
                    "imported",
                    document_id=document_id,
                )

    sync = hub.complete_email_sync_run(run_id, folder_counts)
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
        "run_id": run_id,
        "catalog": catalog_status,
        "sync_status": sync["status"],
        "folder_counts": sync["folder_counts"],
        "item_count": sync["item_count"],
        "error_count": sync["error_count"],
        "ingest": ingest,
        "attributions": attribution_counts,
        "policy_version": current["version"],
        "errors": errors,
        "content_echoed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Import an explicitly exported email folder")
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--source-config", type=Path, required=True)
    parser.add_argument("--window-start", required=True)
    parser.add_argument("--window-end", required=True)
    parser.add_argument("--account-ref", default="mentor-local-export")
    parser.add_argument("--fallback-source-id", default="mentor_general_attachments")
    args = parser.parse_args()
    print(json.dumps(run(args), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
