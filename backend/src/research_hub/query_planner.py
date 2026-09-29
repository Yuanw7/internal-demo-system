from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .util import query_expression


DEFAULT_CONCEPT_PATH = Path(__file__).resolve().parent / "config" / "retrieval_concepts.json"


@dataclass(frozen=True)
class QueryPlan:
    original: str
    lexical_expression: str
    semantic_text: str
    matched_concepts: tuple[str, ...]


def _quoted(term: str) -> str:
    return '"' + term.replace('"', '""') + '"'


def _term_expression(term: str) -> str:
    planned = query_expression(term)
    return planned or _quoted(term.casefold())


def _concept_expression(terms: list[str]) -> str:
    expressions = [_term_expression(term) for term in terms]
    return expressions[0] if len(expressions) == 1 else "(" + " OR ".join(expressions) + ")"


@lru_cache(maxsize=8)
def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _has_alias(query: str, alias: str) -> bool:
    folded = query.casefold()
    candidate = alias.casefold()
    if re.fullmatch(r"[a-z0-9][a-z0-9 ._-]*", candidate):
        return bool(re.search(r"(?<![a-z0-9])" + re.escape(candidate) + r"(?![a-z0-9])", folded))
    return candidate in folded


def plan_query(query: str, concept_path: Path = DEFAULT_CONCEPT_PATH) -> QueryPlan:
    """Turn a short investment-research query into lexical and semantic retrieval views."""
    config = _load(str(concept_path))
    matched = [
        concept
        for concept in config.get("concepts", [])
        if any(_has_alias(query, alias) for alias in concept.get("aliases", []))
    ]
    lexical = (
        " AND ".join(
            _concept_expression(list(dict.fromkeys([*concept["aliases"], *concept["terms"]])))
            for concept in matched
        )
        if matched
        else query_expression(query)
    )
    enrichments = [
        term
        for concept in matched
        for term in [*concept.get("aliases", []), *concept.get("terms", [])]
    ]
    semantic = " | ".join(dict.fromkeys([query.strip(), *enrichments]))
    return QueryPlan(
        original=query,
        lexical_expression=lexical,
        semantic_text=semantic,
        matched_concepts=tuple(concept["id"] for concept in matched),
    )


def concept_version(concept_path: Path = DEFAULT_CONCEPT_PATH) -> str:
    return str(_load(str(concept_path)).get("version", "unknown"))
