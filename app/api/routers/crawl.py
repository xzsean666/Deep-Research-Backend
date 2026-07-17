from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response

from app.api.deps import DbSessionDep, SettingsDep, require_api_key
from app.models import JobType
from app.repositories import crawl_job_repository, document_repository
from app.schemas.crawl import CrawlRequest, CrawlResponse
from app.services.crawl import guard_url
from app.services.document import normalize_url

router = APIRouter(prefix="/v1", tags=["crawl"], dependencies=[Depends(require_api_key)])


@router.post("/crawl", response_model=CrawlResponse, status_code=202)
async def create_crawl(
    body: CrawlRequest, response: Response, session: DbSessionDep, settings: SettingsDep
) -> CrawlResponse:
    normalized = normalize_url(body.url)
    existing = (
        None
        if body.refresh
        else await document_repository.get_by_normalized_url(session, normalized)
    )

    now = datetime.now(UTC)
    if existing is not None and existing.expires_at > now:
        response.status_code = 200
        return CrawlResponse(document_id=existing.id, status="cached", job_id=None)

    # Raises CrawlBlockedError on an SSRF-guarded URL — handled globally,
    # translated to 400 CRAWL_BLOCKED (app/api/errors.py). Checked here,
    # before queuing, so the caller gets an immediate answer instead of a
    # job that's doomed to fail.
    await guard_url(body.url)

    job_type = JobType.REFRESH if existing is not None else JobType.CRAWL
    job = await crawl_job_repository.create(
        session, type_=job_type, url=body.url, max_attempts=settings.job_max_attempts
    )
    return CrawlResponse(
        document_id=existing.id if existing is not None else None, status="queued", job_id=job.id
    )
