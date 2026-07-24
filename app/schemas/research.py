from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from app.config import ExecutionMode
from app.models import SourceType


class RetrievalMode(StrEnum):
    ONLINE = "online"
    LOCAL = "local"
    SEMANTIC = "semantic"  # not implemented in MVP — embeddings deferred, see docs/nextsession.md


class ResearchDocumentStatus(StrEnum):
    CACHED = "cached"
    CRAWLED = "crawled"
    PENDING = "pending"
    FAILED = "failed"
    # A result answered inline by a provider that computes its own answer
    # (e.g. the weather-forecast provider) rather than crawling a webpage —
    # see research_service.py's bypass of the cache/crawl pipeline for these.
    COMPUTED = "computed"


class ResearchStatus(StrEnum):
    COMPLETE = "complete"
    COMPLETE_WITH_FAILURES = "complete_with_failures"
    PARTIAL = "partial"


class WeatherExtremum(StrEnum):
    HIGHEST = "highest"
    LOWEST = "lowest"


class WeatherHint(BaseModel):
    """Structured parameters for the weather-forecast search provider,
    parsed by the calling trading bot from a weather-bracket market's own
    question text (city/extremum/threshold) and end_date (target date) —
    NOT re-derived here from the free-text `query`, which may be an
    LLM-generated keyword extraction with no guaranteed structure. Field
    names match the Rust `WeatherHint` struct exactly."""

    city: str
    market_end_date_utc: datetime
    extremum: WeatherExtremum
    threshold_celsius: float


class ResearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=20)
    refresh: bool = False
    # None means "use RESEARCH_EXECUTION_MODE_DEFAULT" (SPEC.md §9) — the
    # router resolves this, not the schema.
    execution_mode: ExecutionMode | None = None
    mode: RetrievalMode = RetrievalMode.ONLINE
    # Only ever consumed by the weather-forecast provider (see
    # composite_provider.py's per-source forwarding) — every other search
    # source ignores this field entirely.
    hints: WeatherHint | None = None


class ResearchDocument(BaseModel):
    id: UUID | None = None
    url: str
    normalized_url: str
    title: str | None = None
    summary: str | None = None
    markdown: str | None = None
    markdown_truncated: bool = False
    status: ResearchDocumentStatus
    source_type: SourceType | None = None
    search_rank: int | None = None
    semantic_score: float | None = None
    fetched_at: datetime | None = None
    expires_at: datetime | None = None
    published_at: datetime | None = None
    error: str | None = None
    job_id: UUID | None = None


class ResearchResponse(BaseModel):
    query: str
    execution_mode: ExecutionMode
    status: ResearchStatus
    cached: int = 0
    crawled: int = 0
    pending: int = 0
    failed: int = 0
    computed: int = 0
    documents: list[ResearchDocument]
