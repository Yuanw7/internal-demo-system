from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def stable_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: str | bytes) -> str:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(raw).hexdigest()


def search_tokens(text: str) -> str:
    """Generate deterministic ASCII words and overlapping Han bigrams for FTS5."""
    words = re.findall(r"[a-z0-9]+", text.casefold())
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        words.extend(run[index : index + 2] for index in range(len(run) - 1))
        words.extend(run)
    return " ".join(dict.fromkeys(words))


def query_expression(text: str) -> str:
    """Build OR-within-language-runs and AND-between-runs for natural bilingual queries."""
    groups: list[list[str]] = []
    stopwords = {
        "a", "an", "and", "are", "about", "did", "does", "for", "how", "is", "me",
        "of", "please", "tell", "the", "to", "was", "were", "what",
    }
    for word in re.findall(r"[a-z0-9]+", text.casefold()):
        if word not in stopwords:
            groups.append([word])
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        if len(run) <= 2:
            groups.append([run])
        else:
            groups.append(list(dict.fromkeys(run[index : index + 2] for index in range(len(run) - 1))))
    expressions = []
    for group in groups:
        quoted = [f'"{token}"' for token in group]
        expressions.append(quoted[0] if len(quoted) == 1 else "(" + " OR ".join(quoted) + ")")
    return " AND ".join(expressions)
