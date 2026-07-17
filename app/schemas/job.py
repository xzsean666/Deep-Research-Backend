from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models import JobStatus, JobType


class JobResponse(BaseModel):
    id: UUID
    type: JobType
    status: JobStatus
    attempts: int
    max_attempts: int
    created_at: datetime
    updated_at: datetime
    error: str | None
    document_id: UUID | None
