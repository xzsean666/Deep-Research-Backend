from datetime import datetime
from enum import StrEnum

from sqlalchemy import Computed, DateTime, Index, Text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SourceType(StrEnum):
    DOCS = "docs"
    GITHUB = "github"
    BLOG = "blog"
    NEWS = "news"
    OTHER = "other"


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (Index("ix_documents_search_vector", "search_vector", postgresql_using="gin"),)

    url: Mapped[str] = mapped_column(Text)
    normalized_url: Mapped[str] = mapped_column(Text, unique=True, index=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    markdown: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    source_type: Mapped[SourceType] = mapped_column(Text)
    doc_metadata: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('english', coalesce(title, '') || ' ' || coalesce(markdown, ''))",
            persisted=True,
        ),
    )
