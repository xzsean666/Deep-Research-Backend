from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models import SourceType


class DocumentListItem(BaseModel):
    id: UUID
    url: str
    title: str | None
    fetched_at: datetime


class DocumentListResponse(BaseModel):
    items: list[DocumentListItem]
    next_cursor: str | None


class DocumentDetail(BaseModel):
    id: UUID
    url: str
    normalized_url: str
    title: str | None
    markdown: str
    summary: str
    source_type: SourceType
    metadata: dict
    fetched_at: datetime
    expires_at: datetime
