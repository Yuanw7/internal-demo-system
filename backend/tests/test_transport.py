from __future__ import annotations

import json
import sys

import pytest

from research_hub.models import DocumentInput, IngestRequest, SourceDefinition
from research_hub.service import RetrievalHub


@pytest.fixture
def hub(tmp_path):
    service = RetrievalHub(tmp_path / "hub")
    service.upsert_source(SourceDefinition(id="demo", name="Demo", kind="demo"))
    service.ingest(
        IngestRequest(
            source_id="demo",
            documents=[DocumentInput(external_id="one", title="Evidence", body="芯片需求证据。")],
        )
    )
    return service


def test_http_contract_auth_and_policy(hub):
    pytest.importorskip("mcp")
    from fastapi.testclient import TestClient

    from research_hub.api import create_app

    read = {"Authorization": "Bearer " + "r" * 40}
    admin = {"Authorization": "Bearer " + "a" * 40}
    with TestClient(create_app(hub, "r" * 40, "a" * 40)) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/api/status").status_code == 401
        assert client.get("/api/status", headers=read).json()["documents"] == 1
        response = client.post("/api/search", headers=read, json={"query": "芯片"})
        assert response.status_code == 200 and response.json()["policy_version"] == 1
        update = {"expected_version": 1, "policy": {"source_weights": {"demo": 2}}}
        assert client.put("/api/policy", headers=read, json=update).status_code == 403
        assert client.put("/api/policy", headers=admin, json=update).json()["version"] == 2
        assert client.put("/api/policy", headers=admin, json=update).status_code == 409
        assert client.post("/mcp", json={}).status_code == 401


def test_loopback_local_no_auth_mode_keeps_token_mode_optional(hub):
    pytest.importorskip("mcp")
    from fastapi.testclient import TestClient

    from research_hub.api import create_app

    with TestClient(create_app(hub, "", "", local_no_auth=True)) as client:
        assert client.get("/api/status").json()["documents"] == 1
        response = client.post("/api/search", json={"query": "芯片"})
        assert response.status_code == 200
        update = {"expected_version": 1, "policy": {"source_weights": {"demo": 2}}}
        assert client.put("/api/policy", json=update).json()["version"] == 2


def test_ingestion_monitoring_api_and_admin_retry(hub):
    pytest.importorskip("mcp")
    from fastapi.testclient import TestClient

    from research_hub.api import create_app

    hub.upsert_ingestion_connector(
        "fixture_folder", "Fixture Folder", "local_folder", semantic_required=True
    )
    batch_id = hub.create_ingestion_batch("fixture_folder", "manual")
    discovered = hub.discover_ingestion_item(
        batch_id,
        external_id="broken.pdf",
        display_name="broken.pdf",
        source_locator="broken.pdf",
        content_fingerprint="fixture-sha",
        input_bytes=12,
        pipeline_version="fixture-v1",
        max_attempts=1,
    )
    hub.start_ingestion_item(discovered["item_id"], "fixture-worker")
    hub.fail_ingestion_item(
        discovered["item_id"],
        error_class="data",
        error_code="pdf_parse_failed",
        error_message="fixture failure",
        retryable=False,
    )

    read = {"Authorization": "Bearer " + "r" * 40}
    admin = {"Authorization": "Bearer " + "a" * 40}
    with TestClient(create_app(hub, "r" * 40, "a" * 40)) as client:
        summary = client.get("/api/ingestion/summary", headers=read)
        assert summary.status_code == 200
        assert summary.json()["counts"]["failed"] == 1
        listed = client.get("/api/ingestion/items?status=failed", headers=read).json()
        item = listed["items"][0]
        detail = client.get(f"/api/ingestion/items/{item['id']}", headers=read).json()
        assert detail["display_name"] == "broken.pdf"
        request = {
            "expected_state_version": item["state_version"],
            "mode": "restart",
            "reason": "fixture repair",
        }
        assert client.post(
            f"/api/ingestion/items/{item['id']}/retry", headers=read, json=request
        ).status_code == 403
        retried = client.post(
            f"/api/ingestion/items/{item['id']}/retry", headers=admin, json=request
        )
        assert retried.status_code == 202
        assert retried.json()["status"] == "retrying"


@pytest.mark.asyncio
async def test_mcp_tools_are_read_only_and_share_service(hub):
    pytest.importorskip("mcp")
    from research_hub.mcp_server import create_mcp

    server = create_mcp(hub)
    tools = await server.list_tools()
    assert {tool.name for tool in tools} == {"search", "fetch", "search_documents"}
    assert all(tool.annotations.readOnlyHint for tool in tools)
    content, structured = await server.call_tool("search", {"query": "芯片"})
    assert json.loads(content[0].text) == structured
    document_id = structured["results"][0]["id"]
    _, fetched = await server.call_tool("fetch", {"id": document_id})
    assert fetched["text"] == hub.fetch(document_id)["text"]


@pytest.mark.asyncio
async def test_real_stdio_transport_can_initialize_list_and_call(hub):
    pytest.importorskip("mcp")
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    parameters = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "research_hub.cli",
            "--data-dir",
            str(hub.database.path.parent),
            "stdio",
        ],
    )
    async with stdio_client(parameters) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert {tool.name for tool in tools.tools} == {"search", "fetch", "search_documents"}
            result = await session.call_tool("search", {"query": "芯片"})
            assert result.structuredContent["results"][0]["title"] == "Evidence"
