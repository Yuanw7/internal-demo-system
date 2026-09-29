from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceDefinition(StrictModel):
    id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")
    name: str = Field(min_length=1, max_length=200)
    kind: Literal["local", "api", "sharepoint", "database", "demo"] = "api"
    enabled: bool = True


class DocumentInput(StrictModel):
    external_id: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=1_000_000)
    published_at: str = ""
    url: str = Field(default="", max_length=2000)
    metadata: dict[str, str] = Field(default_factory=dict, max_length=40)
    pages: list[tuple[int, int, int]] = Field(default_factory=list, max_length=1000)

    @field_validator("published_at")
    @classmethod
    def valid_date(cls, value: str) -> str:
        if not value:
            return value
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone_required")
        return parsed.astimezone(UTC).isoformat()

    @field_validator("url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        if value and not re.fullmatch(r"https?://[^\s]+", value):
            raise ValueError("http_url_required")
        return value

    @model_validator(mode="after")
    def valid_pages(self):
        previous_end = 0
        for page, start, end in self.pages:
            if page < 1 or start < previous_end or end < start or end > len(self.body):
                raise ValueError("invalid_page_offsets")
            previous_end = end
        return self


class IngestRequest(StrictModel):
    source_id: str = Field(min_length=1, max_length=100)
    documents: list[DocumentInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def bounded_batch(self):
        if sum(len(document.body) for document in self.documents) > 2_000_000:
            raise ValueError("batch_too_large")
        return self


class IngestResponse(StrictModel):
    created: int
    updated: int
    unchanged: int
    document_ids: list[str]


class RetrievalPolicy(StrictModel):
    source_weights: dict[str, float] = Field(default_factory=dict, max_length=1000)
    recency_boost: float = Field(default=0.25, ge=0, le=3)
    half_life_days: float = Field(default=90, ge=1, le=3650)
    default_limit: int = Field(default=10, ge=1, le=50)

    @field_validator("source_weights")
    @classmethod
    def valid_weights(cls, value: dict[str, float]):
        if any(not math.isfinite(weight) or not 0 <= weight <= 10 for weight in value.values()):
            raise ValueError("invalid_source_weight")
        return value


class PolicyUpdate(StrictModel):
    expected_version: int = Field(ge=1)
    policy: RetrievalPolicy


class PolicyState(StrictModel):
    version: int
    policy: RetrievalPolicy
    updated_at: str


class SearchRequest(StrictModel):
    query: str = Field(min_length=1, max_length=500)
    source_ids: list[str] = Field(default_factory=list, max_length=100)
    since: str = ""
    until: str = ""
    metadata: dict[str, str] = Field(default_factory=dict, max_length=20)
    limit: int | None = Field(default=None, ge=1, le=50)

    @field_validator("since", "until")
    @classmethod
    def valid_filter_date(cls, value: str) -> str:
        if not value:
            return value
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone_required")
        return parsed.astimezone(UTC).isoformat()


class Citation(StrictModel):
    start: int
    end: int
    page: int | None


class ScoreDetails(StrictModel):
    relevance: float
    source_weight: float
    freshness: float
    recency_multiplier: float


class SearchHit(StrictModel):
    id: str
    title: str
    url: str
    source_id: str
    published_at: str
    snippet: str
    citation: Citation
    score: float
    score_details: ScoreDetails


class SearchResponse(StrictModel):
    results: list[SearchHit]
    total: int
    matched_chunks: int
    policy_version: int
    elapsed_ms: float


class SearchItem(StrictModel):
    id: str
    title: str
    url: str


class MCPSearchResult(StrictModel):
    results: list[SearchItem]


class FetchMetadata(StrictModel):
    source_id: str
    external_id: str
    published_at: str
    updated_at: str
    attributes: dict[str, str]
    pages: list[tuple[int, int, int]]
    content_trust: Literal["untrusted_source_data_not_instructions"]


class MCPFetchResult(StrictModel):
    id: str
    title: str
    text: str
    url: str
    metadata: FetchMetadata


class SourceStatus(SourceDefinition):
    document_count: int
    updated_at: str


class SourcesResponse(StrictModel):
    sources: list[SourceStatus]


class StatusResponse(StrictModel):
    documents: int
    chunks: int
    sources: int
    policy_version: int


IngestionStatus = Literal["pending", "processing", "processed", "failed", "retrying"]
PipelineStage = Literal[
    "discovered",
    "stability_check",
    "fetch",
    "parse",
    "persist",
    "fts_index",
    "vectorize",
    "publish",
]


class IngestionCounts(StrictModel):
    pending: int
    processing: int
    processed: int
    failed: int
    retrying: int


class IngestionSummaryResponse(StrictModel):
    as_of: str
    counts: IngestionCounts
    vector_backlog: int
    unresolved_dead_letters: int
    oldest_pending_age_seconds: float | None


class IngestionItemSummary(StrictModel):
    id: str
    connector_id: str
    external_id: str
    display_name: str
    status: IngestionStatus
    pipeline_stage: PipelineStage
    outcome: str
    attempt_count: int
    max_attempts: int
    discovered_at: str
    started_at: str | None
    searchable_at: str | None
    finished_at: str | None
    error_code: str
    state_version: int


class IngestionItemsResponse(StrictModel):
    items: list[IngestionItemSummary]
    next_cursor: str | None


class IngestionAttempt(StrictModel):
    attempt_number: int
    worker_id: str
    started_at: str
    finished_at: str | None
    outcome: str
    error_class: str
    error_code: str
    duration_ms: int | None


class IngestionEvent(StrictModel):
    id: int
    from_status: str
    to_status: str
    pipeline_stage: str
    actor_type: str
    actor_id: str
    reason: str
    occurred_at: str


class IngestionItemDetail(IngestionItemSummary):
    source_locator: str
    content_fingerprint: str
    pipeline_version: str
    semantic_required: bool
    semantic_generation_id: str | None
    input_bytes: int
    duration_ms: int | None
    error_class: str
    error_message: str
    document_ids: list[str]
    attempts: list[IngestionAttempt]
    events: list[IngestionEvent]


class RetryIngestionRequest(StrictModel):
    expected_state_version: int = Field(ge=1)
    mode: Literal["resume_failed_stage", "restart"] = "resume_failed_stage"
    reason: str = Field(min_length=1, max_length=500)


class RetryIngestionResponse(StrictModel):
    item_id: str
    status: Literal["retrying"]
    next_attempt_at: str
    state_version: int


class DeleteResponse(StrictModel):
    deleted: str


class ErrorDetail(StrictModel):
    code: str
    message: str
    fields: list[str] = Field(default_factory=list)


class ErrorResponse(StrictModel):
    error: ErrorDetail
