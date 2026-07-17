import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_sessionmaker
from app.repositories import crawl_job_repository, document_repository
from app.services.crawl import CrawlBlockedError, CrawlFetchError, CrawlProvider, get_crawl_provider
from app.services.document import classify_source_type, compute_expires_at, normalize_url

logger = logging.getLogger(__name__)

_SUMMARY_MAX_CHARS = 500


def _make_summary(markdown: str) -> str:
    return " ".join(markdown.split())[:_SUMMARY_MAX_CHARS]


async def process_one_job(
    session: AsyncSession, crawl_provider: CrawlProvider, settings: Settings
) -> bool:
    """Claim and fully process one due job, if any. Returns whether a job was claimed.

    Worker pipeline per ARCHITECTURE.md §9: claim -> crawl (guard happens
    inside the provider) -> upsert document -> mark job completed/failed.
    """
    job = await crawl_job_repository.claim_next(session)
    if job is None:
        return False

    try:
        result = await crawl_provider.crawl(job.url)
    except CrawlBlockedError as exc:
        await crawl_job_repository.mark_failed(session, job.id, str(exc), permanent=True)
        return True
    except CrawlFetchError as exc:
        await crawl_job_repository.mark_failed(session, job.id, str(exc))
        return True
    except Exception as exc:  # noqa: BLE001 - never let an unknown error vanish a job silently
        logger.exception("unexpected error crawling job %s (%s)", job.id, job.url)
        await crawl_job_repository.mark_failed(session, job.id, f"unexpected error: {exc}")
        return True

    fetched_at = datetime.now(UTC)
    source_type = classify_source_type(job.url)
    document = await document_repository.upsert(
        session,
        url=job.url,
        normalized_url=normalize_url(job.url),
        title=result.title,
        markdown=result.markdown,
        summary=_make_summary(result.markdown),
        source_type=source_type,
        doc_metadata=result.metadata,
        fetched_at=fetched_at,
        expires_at=compute_expires_at(source_type, fetched_at, settings),
    )
    await crawl_job_repository.mark_completed(session, job.id, document.id)
    return True


async def run_worker_loop(stop_event: asyncio.Event | None = None) -> None:
    """Pull-based job claim loop. Any number of instances may run this
    concurrently against the same database (ARCHITECTURE.md §9) — there is
    no coordination beyond the FOR UPDATE SKIP LOCKED claim query.
    """
    settings = get_settings()
    crawl_provider = get_crawl_provider(settings)
    sessionmaker = get_sessionmaker()

    while stop_event is None or not stop_event.is_set():
        try:
            async with sessionmaker() as session:
                claimed = await process_one_job(session, crawl_provider, settings)
        except Exception:  # noqa: BLE001 - a bad iteration (e.g. a DB blip) must not kill the worker
            logger.exception("worker iteration failed, will retry after the poll interval")
            claimed = False
        if not claimed:
            await asyncio.sleep(settings.worker_poll_interval_seconds)
