from __future__ import annotations

import hmac
import sqlite3
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.exceptions import HTTPException as StarletteHTTPException

from .mcp_server import create_mcp
from .models import (
    DeleteResponse,
    ErrorResponse,
    IngestRequest,
    IngestResponse,
    MCPFetchResult,
    PolicyState,
    PolicyUpdate,
    SearchRequest,
    SearchResponse,
    SourceDefinition,
    SourcesResponse,
    StatusResponse,
)
from .service import HubError, RetrievalHub


def create_app(
    hub: RetrievalHub,
    read_token: str,
    admin_token: str,
    allowed_origins: list[str] | None = None,
) -> FastAPI:
    if len(read_token) < 32 or len(admin_token) < 32 or read_token == admin_token:
        raise ValueError("distinct_tokens_of_at_least_32_characters_required")
    mcp = create_mcp(
        hub,
        allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*"],
        allowed_origins=["http://127.0.0.1:*", "http://localhost:*"],
    )
    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(
        title="Internal Research Data API",
        version="1.0.0",
        lifespan=lifespan,
        description="Local Retrieval Hub. HTTP and MCP share one database and ranking policy.",
        responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 413, 422, 503)},
    )
    security = HTTPBearer(auto_error=False)

    def error(code: str, status: int, fields=None, headers=None):
        return JSONResponse(
            {"error": {"code": code, "message": code, "fields": fields or []}},
            status_code=status,
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", **(headers or {})},
        )

    def matches(value: str, expected: str) -> bool:
        return hmac.compare_digest(value.encode(), expected.encode())

    def read_access(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
        value = credentials.credentials if credentials else ""
        if not (matches(value, read_token) or matches(value, admin_token)):
            raise HTTPException(401, "unauthorized", headers={"WWW-Authenticate": "Bearer"})

    def admin_access(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
        value = credentials.credentials if credentials else ""
        if not matches(value, admin_token):
            raise HTTPException(403, "admin_token_required")

    @app.middleware("http")
    async def protect_mcp_and_bound_body(request: Request, call_next):
        if request.url.path == "/mcp" or request.url.path.startswith("/mcp/"):
            header = request.headers.get("authorization", "")
            value = header[7:] if header.lower().startswith("bearer ") else ""
            if not (matches(value, read_token) or matches(value, admin_token)):
                return error("unauthorized", 401, headers={"WWW-Authenticate": "Bearer"})
        if request.method in {"POST", "PUT", "PATCH"}:
            size = 0
            parts = []
            async for chunk in request.stream():
                size += len(chunk)
                if size > 12_000_000:
                    return error("request_too_large", 413)
                parts.append(chunk)
            request._body = b"".join(parts)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(HubError)
    async def hub_error(request, exc):
        code = str(exc)
        status = 409 if code == "policy_version_conflict" else 404 if code.endswith("not_found") else 422
        return error(code, status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return error("validation_error", 422, [".".join(map(str, item["loc"])) for item in exc.errors()])

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        return error(str(exc.detail), exc.status_code, headers=exc.headers)

    @app.exception_handler(sqlite3.Error)
    async def database_error(request, exc):
        return error("storage_unavailable", 503)

    @app.get("/healthz")
    def health():
        return {"status": "ok", "api_version": "1.0.0"}

    @app.get("/api/status", dependencies=[Depends(read_access)], response_model=StatusResponse)
    def status():
        return hub.stats()

    @app.get("/api/sources", dependencies=[Depends(read_access)], response_model=SourcesResponse)
    def sources():
        return {"sources": hub.sources()}

    @app.post("/api/sources", dependencies=[Depends(admin_access)], response_model=SourceDefinition)
    def source(body: SourceDefinition):
        return hub.upsert_source(body)

    @app.post(
        "/api/ingest/documents", dependencies=[Depends(admin_access)], response_model=IngestResponse
    )
    def ingest(body: IngestRequest):
        return hub.ingest(body)

    @app.post("/api/search", dependencies=[Depends(read_access)], response_model=SearchResponse)
    def search(body: SearchRequest):
        return hub.search(body)

    @app.get(
        "/api/documents/{document_id}",
        dependencies=[Depends(read_access)],
        response_model=MCPFetchResult,
    )
    def fetch(document_id: str):
        return hub.fetch(document_id)

    @app.delete(
        "/api/documents/{document_id}",
        dependencies=[Depends(admin_access)],
        response_model=DeleteResponse,
    )
    def delete(document_id: str):
        return hub.delete_document(document_id)

    @app.get("/api/policy", dependencies=[Depends(read_access)], response_model=PolicyState)
    def policy():
        return hub.policy()

    @app.put("/api/policy", dependencies=[Depends(admin_access)], response_model=PolicyState)
    def update_policy(body: PolicyUpdate):
        return hub.update_policy(body)

    app.mount("/", mcp_app)
    if allowed_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins,
            allow_methods=["GET", "POST", "PUT", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
        )
    return app
