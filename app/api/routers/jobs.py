import uuid

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSessionDep, require_api_key
from app.api.errors import NotFoundError
from app.models import JobStatus
from app.repositories import crawl_job_repository
from app.schemas.job import JobResponse

router = APIRouter(prefix="/v1/jobs", tags=["jobs"], dependencies=[Depends(require_api_key)])


def _to_response(job) -> JobResponse:
    return JobResponse(
        id=job.id,
        type=job.type,
        status=job.status,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        created_at=job.created_at,
        updated_at=job.updated_at,
        error=job.error,
        document_id=job.document_id,
    )


@router.get("", response_model=list[JobResponse])
async def list_jobs(
    session: DbSessionDep,
    status: JobStatus = Query(default=JobStatus.DEAD_LETTER),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[JobResponse]:
    jobs = await crawl_job_repository.list_by_status(session, status, limit)
    return [_to_response(job) for job in jobs]


@router.get("/{job_id}", response_model=JobResponse)
async def get_job(job_id: uuid.UUID, session: DbSessionDep) -> JobResponse:
    job = await crawl_job_repository.get_by_id(session, job_id)
    if job is None:
        raise NotFoundError(f"job {job_id} not found")
    return _to_response(job)
