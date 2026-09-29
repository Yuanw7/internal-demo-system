from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_hub.models import SearchRequest  # noqa: E402
from research_hub.service import RetrievalHub  # noqa: E402


QUERIES = (
    ("英伟达具体显卡", ("nvidia", "h100", "h200", "b100", "b200", "gb200", "blackwell")),
    (
        "AI infra power and networking bottlenecks",
        (
            "power",
            "cooling",
            "network",
            "nvlink",
            "infiniband",
            "data center",
            "hbm",
            "server",
            "rack",
        ),
    ),
    ("Nebius capex and GPU capacity", ("nebius", "capex", "gpu", "capacity")),
    ("Snowflake AI product monetization", ("snowflake", "cortex", "ai", "product", "revenue")),
)


class LexicalOnly:
    def is_current(self, _connection):
        return True

    def search(self, _query, limit=300):
        return []


def summarize(response: dict, expected: tuple[str, ...]) -> dict:
    results = response["results"]
    hit_count = 0
    for item in results:
        evidence = (item["title"] + " " + item["snippet"]).casefold()
        hit_count += int(any(term in evidence for term in expected))
    return {
        "result_count": len(results),
        "expected_term_hit_rate": round(hit_count / len(results), 3) if results else 0,
        "elapsed_ms": response["elapsed_ms"],
        "result_ids": [item["id"] for item in results],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    hybrid = RetrievalHub(args.data_dir)
    lexical = RetrievalHub(args.data_dir, semantic_index=LexicalOnly())
    output = []
    for query, expected in QUERIES:
        request = SearchRequest(query=query, limit=10)
        output.append(
            {
                "query": query,
                "lexical": summarize(lexical.search(request), expected),
                "hybrid": summarize(hybrid.search(request), expected),
            }
        )
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
