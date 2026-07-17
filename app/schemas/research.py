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


class ResearchStatus(StrEnum):
    COMPLETE = "complete"
    COMPLETE_WITH_FAILURES = "complete_with_failures"
    PARTIAL = "partial"


class ResearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=20)
    refresh: bool = False
    # None means "use RESEARCH_EXECUTION_MODE_DEFAULT" (SPEC.md §9) — the
    # router resolves this, not the schema.
    execution_mode: ExecutionMode | None = None
    mode: RetrievalMode = RetrievalMode.ONLINE


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
    documents: list[ResearchDocument]
