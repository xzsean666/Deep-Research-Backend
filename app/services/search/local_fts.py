from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Document
from app.repositories import document_repository


async def search_local(session: AsyncSession, query: str, limit: int) -> list[Document]:
    """Local full text search over already-crawled documents. ARCHITECTURE.md §8.2."""
    return await document_repository.search_fts(session, query, limit)
