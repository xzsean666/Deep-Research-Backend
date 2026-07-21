from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ApiKeyStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class ApiKey(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "api_keys"

    key_hash: Mapped[str] = mapped_column(Text, unique=True, index=True)
    label: Mapped[str] = mapped_column(Text)
    rate_limit_per_minute: Mapped[int] = mapped_column(default=60)
    status: Mapped[ApiKeyStatus] = mapped_column(Text, default=ApiKeyStatus.ACTIVE)
    # NULL = permanent (the default) — never expires.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
