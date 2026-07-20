import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document, SourceType


async def get_by_normalized_url(session: AsyncSession, normalized_url: str) -> Document | None:
    stmt = select(Document).where(Document.normalized_url == normalized_url)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_by_id(session: AsyncSession, document_id: uuid.UUID) -> Document | None:
    return await session.get(Document, document_id)


async def upsert(
    session: AsyncSession,
    *,
    url: str,
    normalized_url: str,
    title: str | None,
    markdown: str,
    summary: str,
    source_type: SourceType,
    doc_metadata: dict,
    fetched_at: datetime,
    expires_at: datetime,
    published_at: datetime | None = None,
) -> Document:
    """Insert a document, or refresh it in place if normalized_url already exists.

    `id` is intentionally preserved across a refresh (excluded from the
    conflict update) so existing crawl_jobs.document_id references and any
    caller-held document id stay valid after a TTL refresh.
    """
    stmt = (
        insert(Document)
        .values(
            url=url,
            normalized_url=normalized_url,
            title=title,
            markdown=markdown,
            summary=summary,
            source_type=source_type,
            doc_metadata=doc_metadata,
            fetched_at=fetched_at,
            expires_at=expires_at,
            published_at=published_at,
        )
        .on_conflict_do_update(
            index_elements=[Document.normalized_url],
            set_={
                "url": url,
                "title": title,
                "markdown": markdown,
                "summary": summary,
                "source_type": source_type,
                "metadata": doc_metadata,
                "fetched_at": fetched_at,
                "expires_at": expires_at,
                "published_at": published_at,
            },
        )
        .returning(Document)
    )
    result = await session.execute(stmt)
    await session.commit()
    return result.scalar_one()


async def search_fts(session: AsyncSession, query: str, limit: int) -> list[Document]:
    tsquery = func.websearch_to_tsquery("english", query)
    stmt = select(Document).where(Document.search_vector.bool_op("@@")(tsquery)).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_documents(
    session: AsyncSession,
    *,
    limit: int,
    source_type: SourceType | None = None,
    after_created_at: datetime | None = None,
) -> list[Document]:
    stmt = select(Document).order_by(Document.created_at.desc()).limit(limit)
    if source_type is not None:
        stmt = stmt.where(Document.source_type == source_type)
    if after_created_at is not None:
        stmt = stmt.where(Document.created_at < after_created_at)
    result = await session.execute(stmt)
    return list(result.scalars().all())
