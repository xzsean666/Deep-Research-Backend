import base64
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSessionDep, SettingsDep, require_api_key
from app.api.errors import NotFoundError
from app.models import JobType, SourceType
from app.repositories import crawl_job_repository, document_repository
from app.schemas.document import DocumentDetail, DocumentListItem, DocumentListResponse
from app.schemas.research import ResearchDocument, ResearchDocumentStatus
from app.services.search import search_local

router = APIRouter(
    prefix="/v1/documents", tags=["documents"], dependencies=[Depends(require_api_key)]
)


def _encode_cursor(value: datetime) -> str:
    return base64.urlsafe_b64encode(value.isoformat().encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> datetime:
    return datetime.fromisoformat(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    session: DbSessionDep,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
    source_type: SourceType | None = None,
) -> DocumentListResponse:
    after_created_at = _decode_cursor(cursor) if cursor else None
    docs = await document_repository.list_documents(
        session, limit=limit, source_type=source_type, after_created_at=after_created_at
    )
    next_cursor = _encode_cursor(docs[-1].created_at) if len(docs) == limit else None
    items = [
        DocumentListItem(id=d.id, url=d.url, title=d.title, fetched_at=d.fetched_at) for d in docs
    ]
    return DocumentListResponse(items=items, next_cursor=next_cursor)


@router.get("/search", response_model=list[ResearchDocument])
async def search_documents(
    session: DbSessionDep, q: str = Query(min_length=1), limit: int = Query(default=5, ge=1, le=20)
) -> list[ResearchDocument]:
    docs = await search_local(session, q, limit)
    return [
        ResearchDocument(
            id=d.id,
            url=d.url,
            normalized_url=d.normalized_url,
            title=d.title,
            summary=d.summary,
            markdown=d.markdown,
            status=ResearchDocumentStatus.CACHED,
            source_type=d.source_type,
            fetched_at=d.fetched_at,
            expires_at=d.expires_at,
        )
        for d in docs
    ]


@router.get("/{document_id}", response_model=DocumentDetail)
async def get_document(document_id: uuid.UUID, session: DbSessionDep) -> DocumentDetail:
    doc = await document_repository.get_by_id(session, document_id)
    if doc is None:
        raise NotFoundError(f"document {document_id} not found")
    return DocumentDetail(
        id=doc.id,
        url=doc.url,
        normalized_url=doc.normalized_url,
        title=doc.title,
        markdown=doc.markdown,
        summary=doc.summary,
        source_type=doc.source_type,
        metadata=doc.doc_metadata,
        fetched_at=doc.fetched_at,
        expires_at=doc.expires_at,
    )


@router.post("/{document_id}/refresh", status_code=202)
async def refresh_document(
    document_id: uuid.UUID, session: DbSessionDep, settings: SettingsDep
) -> dict:
    doc = await document_repository.get_by_id(session, document_id)
    if doc is None:
        raise NotFoundError(f"document {document_id} not found")
    job = await crawl_job_repository.create(
        session, type_=JobType.REFRESH, url=doc.url, max_attempts=settings.job_max_attempts
    )
    return {"job_id": job.id}
