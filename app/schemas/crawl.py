from uuid import UUID

from pydantic import BaseModel


class CrawlRequest(BaseModel):
    url: str
    refresh: bool = False


class CrawlResponse(BaseModel):
    document_id: UUID | None
    status: str  # "cached" | "queued"
    job_id: UUID | None
