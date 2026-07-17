import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CrawlJob, JobStatus, JobType

_BACKOFF_BASE_SECONDS = 5
_BACKOFF_MAX_SECONDS = 300


def _backoff_delay(attempts: int) -> timedelta:
    return timedelta(seconds=min(_BACKOFF_BASE_SECONDS * (2**attempts), _BACKOFF_MAX_SECONDS))


async def create(
    session: AsyncSession, *, type_: JobType, url: str, max_attempts: int
) -> CrawlJob:
    job = CrawlJob(type=type_, url=url, max_attempts=max_attempts)
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def get_by_id(session: AsyncSession, job_id: uuid.UUID) -> CrawlJob | None:
    return await session.get(CrawlJob, job_id)


async def get_active_by_url(session: AsyncSession, url: str) -> CrawlJob | None:
    """An in-flight (pending/running) job already targeting this URL, if any.

    Callers should reuse this instead of creating a new job — otherwise
    polling /v1/research for a URL that hasn't resolved yet (the documented
    background-mode pattern, ARCHITECTURE.md §5.2) creates a fresh duplicate
    job on every call instead of waiting on the one already in flight.
    dead_letter/completed jobs are excluded on purpose: a URL whose only
    job already failed permanently should get a fresh set of attempts.
    """
    stmt = (
        select(CrawlJob)
        .where(CrawlJob.url == url, CrawlJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING]))
        .order_by(CrawlJob.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def claim_next(session: AsyncSession) -> CrawlJob | None:
    """Atomically claim one due job for this worker. See ARCHITECTURE.md §9."""
    stmt = (
        select(CrawlJob)
        .where(CrawlJob.status == JobStatus.PENDING, CrawlJob.next_attempt_at <= datetime.now(UTC))
        .order_by(CrawlJob.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    result = await session.execute(stmt)
    job = result.scalar_one_or_none()
    if job is None:
        return None

    job.status = JobStatus.RUNNING
    job.attempts += 1
    await session.commit()
    await session.refresh(job)
    return job


async def mark_completed(session: AsyncSession, job_id: uuid.UUID, document_id: uuid.UUID) -> None:
    job = await session.get(CrawlJob, job_id)
    if job is None:
        return
    job.status = JobStatus.COMPLETED
    job.document_id = document_id
    job.error = None
    await session.commit()


async def mark_failed(
    session: AsyncSession, job_id: uuid.UUID, error: str, *, permanent: bool = False
) -> None:
    """Reschedule with backoff, or move straight to dead_letter.

    `permanent=True` skips retries entirely (e.g. the URL failed the SSRF
    guard — retrying won't change that outcome). Otherwise, dead_letter
    only once max_attempts is exhausted.
    """
    job = await session.get(CrawlJob, job_id)
    if job is None:
        return
    job.error = error
    if permanent or job.attempts >= job.max_attempts:
        job.status = JobStatus.DEAD_LETTER
    else:
        job.status = JobStatus.PENDING
        job.next_attempt_at = datetime.now(UTC) + _backoff_delay(job.attempts)
    await session.commit()


async def list_by_status(session: AsyncSession, status: JobStatus, limit: int) -> list[CrawlJob]:
    stmt = (
        select(CrawlJob)
        .where(CrawlJob.status == status)
        .order_by(CrawlJob.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
