from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ApiKey(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "api_keys"

    key_hash: Mapped[str] = mapped_column(Text, unique=True, index=True)
    label: Mapped[str] = mapped_column(Text)
    rate_limit_per_minute: Mapped[int] = mapped_column(default=60)
