from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal, Sequence


DEFAULT_SOURCE_RANKING_PATH = (
    Path(__file__).resolve().parent / "config" / "source_rankings_v0.json"
)
DEFAULT_SOURCE_RANKING_V1_PATH = (
    Path(__file__).resolve().parent / "config" / "source_rankings_v1.json"
)
SOURCE_ID = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
ResolutionStatus = Literal["matched", "ambiguous", "unmatched"]


def normalize_source_name(value: str) -> str:
    """Normalize only explicit names/aliases; V0 intentionally does no fuzzy matching."""
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


@dataclass(frozen=True)
class InformationSource:
    id: str
    display_name: str
    source_type: str
    priority_tier: int
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class SourceCandidate:
    role: str
    value: str


@dataclass(frozen=True)
class SourceResolution:
    status: ResolutionStatus
    value: str
    normalized_value: str
    source_ids: tuple[str, ...]
    matched_by: str = ""


@dataclass(frozen=True)
class PrimarySourceResolution:
    status: ResolutionStatus
    source: InformationSource | None
    role: str
    value: str
    matched_by: str
    candidate_source_ids: tuple[str, ...]
    checks: tuple[SourceResolution, ...]


class SourceRankingCatalog:
    def __init__(self, raw: dict):
        self.version = str(raw.get("version", "")).strip()
        if not self.version:
            raise ValueError("source_ranking_version_required")

        weights = raw.get("tier_weights")
        if not isinstance(weights, dict) or set(weights) != {"1", "2", "3", "4"}:
            raise ValueError("source_ranking_tier_weights_required")
        self.tier_weights = {int(tier): float(weight) for tier, weight in weights.items()}
        if any(
            not math.isfinite(weight) or not 0 <= weight <= 10
            for weight in self.tier_weights.values()
        ):
            raise ValueError("source_ranking_weight_invalid")

        roles = raw.get("role_precedence")
        if (
            not isinstance(roles, list)
            or not roles
            or any(not isinstance(role, str) or not role.strip() for role in roles)
            or len(set(roles)) != len(roles)
        ):
            raise ValueError("source_ranking_roles_invalid")
        self.role_precedence = tuple(roles)

        records = raw.get("sources")
        if not isinstance(records, list) or not records:
            raise ValueError("source_ranking_sources_required")
        sources: dict[str, InformationSource] = {}
        alias_index: dict[str, list[tuple[str, str]]] = {}
        for item in records:
            if not isinstance(item, dict):
                raise ValueError("source_ranking_source_invalid")
            source_id = str(item.get("id", ""))
            display_name = str(item.get("display_name", "")).strip()
            source_type = str(item.get("source_type", "")).strip()
            priority_tier = item.get("priority_tier")
            aliases = item.get("aliases", [])
            if not SOURCE_ID.fullmatch(source_id) or source_id in sources:
                raise ValueError("source_ranking_source_id_invalid")
            if not display_name or source_type not in self.role_precedence:
                raise ValueError("source_ranking_source_fields_invalid")
            if priority_tier not in self.tier_weights:
                raise ValueError("source_ranking_priority_invalid")
            if not isinstance(aliases, list) or any(
                not isinstance(alias, str) or not alias.strip() for alias in aliases
            ):
                raise ValueError("source_ranking_alias_invalid")
            source = InformationSource(
                id=source_id,
                display_name=display_name,
                source_type=source_type,
                priority_tier=int(priority_tier),
                aliases=tuple(aliases),
            )
            sources[source_id] = source
            labels = [(display_name, "display_name"), *[(alias, "alias") for alias in aliases]]
            for label, matched_by in labels:
                alias_index.setdefault(normalize_source_name(label), []).append(
                    (source_id, matched_by)
                )
        self.sources = sources
        self._alias_index = {
            alias: tuple(dict.fromkeys(matches)) for alias, matches in alias_index.items()
        }
        self._role_order = {role: index for index, role in enumerate(self.role_precedence)}

    def resolve(self, value: str) -> SourceResolution:
        normalized = normalize_source_name(value)
        matches = self._alias_index.get(normalized, ()) if normalized else ()
        source_ids = tuple(dict.fromkeys(source_id for source_id, _ in matches))
        if not source_ids:
            return SourceResolution("unmatched", value, normalized, ())
        if len(source_ids) > 1:
            return SourceResolution("ambiguous", value, normalized, source_ids)
        matched_by = (
            "display_name" if any(kind == "display_name" for _, kind in matches) else "alias"
        )
        return SourceResolution("matched", value, normalized, source_ids, matched_by)

    def resolve_primary(self, candidates: Sequence[SourceCandidate]) -> PrimarySourceResolution:
        ordered = sorted(
            enumerate(candidates),
            key=lambda pair: (self._role_order.get(pair[1].role, len(self._role_order)), pair[0]),
        )
        checks: list[SourceResolution] = []
        first_ambiguous: tuple[SourceCandidate, SourceResolution] | None = None
        for _, candidate in ordered:
            resolved = self.resolve(candidate.value)
            checks.append(resolved)
            if resolved.status == "matched":
                source = self.sources[resolved.source_ids[0]]
                return PrimarySourceResolution(
                    "matched",
                    source,
                    candidate.role,
                    candidate.value,
                    resolved.matched_by,
                    resolved.source_ids,
                    tuple(checks),
                )
            if resolved.status == "ambiguous" and first_ambiguous is None:
                first_ambiguous = (candidate, resolved)
        if first_ambiguous:
            candidate, resolved = first_ambiguous
            return PrimarySourceResolution(
                "ambiguous",
                None,
                candidate.role,
                candidate.value,
                "",
                resolved.source_ids,
                tuple(checks),
            )
        return PrimarySourceResolution("unmatched", None, "", "", "", (), tuple(checks))

    def policy_weights(self, source_ids: Sequence[str] | None = None) -> dict[str, float]:
        requested = set(source_ids) if source_ids is not None else set(self.sources)
        unknown = requested - self.sources.keys()
        if unknown:
            raise ValueError("source_ranking_unknown_source")
        return {
            source_id: self.tier_weights[self.sources[source_id].priority_tier]
            for source_id in sorted(requested)
        }


@lru_cache(maxsize=8)
def _load(path: str) -> SourceRankingCatalog:
    return SourceRankingCatalog(json.loads(Path(path).read_text(encoding="utf-8")))


def load_source_ranking_catalog(
    path: Path = DEFAULT_SOURCE_RANKING_PATH,
) -> SourceRankingCatalog:
    return _load(str(path.resolve()))


METADATA_SOURCE_FIELDS: tuple[tuple[str, str], ...] = (
    ("analyst", "analyst"),
    ("report_author", "report_author"),
    ("email_from_address", "email_sender"),
    ("email_from_name", "email_sender"),
    ("institution", "institution"),
    ("internal_note", "internal_note"),
    ("data_provider", "data_provider"),
    ("research_platform", "research_platform"),
    ("news_source", "news"),
    ("social_media_source", "social_media"),
    ("manual_upload_source", "manual_upload"),
)


def source_candidates_from_metadata(metadata: dict[str, str]) -> tuple[SourceCandidate, ...]:
    """Build explicit candidates without inferring identities from free-form body text."""
    candidates: list[SourceCandidate] = []
    seen: set[tuple[str, str]] = set()
    for field, role in METADATA_SOURCE_FIELDS:
        value = metadata.get(field, "").strip()
        key = (role, normalize_source_name(value))
        if value and key not in seen:
            candidates.append(SourceCandidate(role, value))
            seen.add(key)
    return tuple(candidates)
