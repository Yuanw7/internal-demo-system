#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


async def check(plugin_root: Path) -> dict:
    environment = dict(os.environ)
    parameters = StdioServerParameters(
        command="bash",
        args=["./scripts/run-mcp.sh"],
        cwd=str(plugin_root.resolve()),
        env=environment,
    )
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            listed = await session.list_tools()
            tool_names = {tool.name for tool in listed.tools}
            if tool_names != {"search", "fetch", "search_documents"}:
                raise RuntimeError("mcp_tool_set_mismatch")
            search = await session.call_tool(
                "search_documents",
                {"request": {"query": "Aurora Compute", "limit": 4}},
            )
            if search.isError or not search.structuredContent:
                raise RuntimeError("mcp_search_failed")
            results = search.structuredContent["results"]
            if len(results) != 4:
                raise RuntimeError("mcp_search_result_mismatch")
            fetched = await session.call_tool("fetch", {"id": results[0]["id"]})
            if fetched.isError or not fetched.structuredContent:
                raise RuntimeError("mcp_fetch_failed")
            return {
                "status": "pass",
                "tools": sorted(tool_names),
                "policy_version": search.structuredContent["policy_version"],
                "search_results": len(results),
                "fetch_id_matches": fetched.structuredContent["id"] == results[0]["id"],
                "content_trust": fetched.structuredContent["metadata"]["content_trust"],
            }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(check(args.plugin_root)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
