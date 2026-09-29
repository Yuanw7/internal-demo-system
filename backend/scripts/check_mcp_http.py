from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def check(url: str, token: str, query: str):
    async with httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}) as client:
        async with streamable_http_client(url, http_client=client) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                result = await session.call_tool("search_documents", {"request": {"query": query}})
                payload = result.structuredContent
                return {
                    "status": "passed",
                    "tools": sorted(tool.name for tool in tools.tools),
                    "policy_version": payload["policy_version"],
                    "result_ids": [item["id"] for item in payload["results"]],
                }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8765/mcp")
    parser.add_argument("--credentials", type=Path, required=True)
    parser.add_argument("--query", default="芯片")
    args = parser.parse_args()
    token = json.loads(args.credentials.read_text(encoding="utf-8"))["read_token"]
    print(json.dumps(asyncio.run(check(args.url, token, args.query)), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
