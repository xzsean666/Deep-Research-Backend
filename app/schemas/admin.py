from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models import ApiKeyStatus


class CreateApiKeyRequest(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    rate_limit_per_minute: int = Field(default=60, ge=1)
    # None (default) = permanent, never expires.
    expires_at: datetime | None = None


class ApiKeyCreatedResponse(BaseModel):
    id: UUID
    label: str
    status: ApiKeyStatus
    rate_limit_per_minute: int
    expires_at: datetime | None
    created_at: datetime
    # Shown exactly once, here — never retrievable again after this response.
    raw_key: str


class ApiKeyResponse(BaseModel):
    id: UUID
    label: str
    status: ApiKeyStatus
    rate_limit_per_minute: int
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class UpdateApiKeyRequest(BaseModel):
    """Only fields actually present in the request body are applied — use
    model_fields_set to distinguish "not provided" from "explicitly set to
    null" for expires_at (null means "make it permanent")."""

    status: ApiKeyStatus | None = None
    expires_at: datetime | None = None
