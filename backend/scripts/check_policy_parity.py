from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def mcp_search(url: str, token: str, query: str):
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}) as client:
        async with streamable_http_client(url, http_client=client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("search_documents", {"request": {"query": query}})
                return result.structuredContent


async def run(base_url: str, credentials_path: Path, query: str):
    credentials = json.loads(credentials_path.read_text(encoding="utf-8"))
    read_headers = {"Authorization": f"Bearer {credentials['read_token']}"}
    admin_headers = {"Authorization": f"Bearer {credentials['admin_token']}"}
    async with httpx.AsyncClient(base_url=base_url) as client:
        original = (await client.get("/api/policy", headers=read_headers)).json()
        sources = (await client.get("/api/sources", headers=read_headers)).json()["sources"]
        weights = {source["id"]: index + 1 for index, source in enumerate(sources)}
        candidate = dict(original["policy"])
        candidate["source_weights"] = weights
        updated = None
        try:
            response = await client.put(
                "/api/policy",
                headers=admin_headers,
                json={"expected_version": original["version"], "policy": candidate},
            )
            response.raise_for_status()
            updated = response.json()
            http_result = (
                await client.post("/api/search", headers=read_headers, json={"query": query})
            ).json()
            mcp_result = await mcp_search(
                base_url.rstrip("/") + "/mcp", credentials["read_token"], query
            )
            assert http_result["policy_version"] == mcp_result["policy_version"] == updated["version"]
            assert [item["id"] for item in http_result["results"]] == [
                item["id"] for item in mcp_result["results"]
            ]
            return {
                "status": "passed",
                "policy_version": updated["version"],
                "result_ids": [item["id"] for item in http_result["results"]],
            }
        finally:
            if updated is not None:
                restore = await client.put(
                    "/api/policy",
                    headers=admin_headers,
                    json={"expected_version": updated["version"], "policy": original["policy"]},
                )
                restore.raise_for_status()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--query", default="芯片需求")
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.base_url, args.credentials, args.query)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
