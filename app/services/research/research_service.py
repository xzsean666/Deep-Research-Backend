import asyncio
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import ExecutionMode, Settings
from app.models import Document, JobStatus, JobType
from app.repositories import crawl_job_repository, document_repository
from app.schemas.research import (
    ResearchDocument,
    ResearchDocumentStatus,
    ResearchResponse,
    ResearchStatus,
    RetrievalMode,
    WeatherHint,
)
from app.services.document import normalize_url
from app.services.search import SearchProvider, SearchResult, search_local
from app.services.search.composite_provider import CompositeSearchProvider

# SPEC.md §3 — full markdown is inlined up to this size; beyond it the
# caller is pointed at GET /v1/documents/{id} instead. Not yet a config
# knob (no other MVP behavior depends on tuning it); promote to Settings
# if that changes.
_INLINE_MARKDOWN_MAX_BYTES = 200_000


class SemanticSearchNotImplementedError(Exception):
    """mode='semantic' requires an embedding provider, deferred post-MVP."""


def _cached_or_crawled_document(
    search_result: SearchResult | None,
    document: Document,
    status: ResearchDocumentStatus,
) -> ResearchDocument:
    markdown = document.markdown
    truncated = False
    if len(markdown.encode("utf-8")) > _INLINE_MARKDOWN_MAX_BYTES:
        markdown = None
        truncated = True

    return ResearchDocument(
        id=document.id,
        url=document.url,
        normalized_url=document.normalized_url,
        title=document.title,
        summary=document.summary,
        markdown=markdown,
        markdown_truncated=truncated,
        status=status,
        source_type=document.source_type,
        search_rank=search_result.rank if search_result else None,
        fetched_at=document.fetched_at,
        expires_at=document.expires_at,
        published_at=document.published_at,
    )


def _pending_document(search_result: SearchResult, normalized_url: str, job_id) -> ResearchDocument:
    return ResearchDocument(
        url=search_result.url,
        normalized_url=normalized_url,
        status=ResearchDocumentStatus.PENDING,
        search_rank=search_result.rank,
        job_id=job_id,
    )


def _failed_document(
    search_result: SearchResult, normalized_url: str, error: str | None
) -> ResearchDocument:
    # The crawl failed, but the search step already had a title/snippet for
    # this URL — falling back to it beats returning nothing. status stays
    # FAILED and error stays populated, so callers can still tell this is
    # degraded (search-snippet-only) content rather than a full crawl.
    return ResearchDocument(
        url=search_result.url,
        normalized_url=normalized_url,
        title=search_result.title,
        summary=search_result.snippet,
        status=ResearchDocumentStatus.FAILED,
        search_rank=search_result.rank,
        error=error,
    )


async def _poll_until_terminal(
    sessionmaker: async_sessionmaker[AsyncSession], job_id, poll_interval_seconds: float
):
    while True:
        async with sessionmaker() as session:
            job = await crawl_job_repository.get_by_id(session, job_id)
        if job.status in (JobStatus.COMPLETED, JobStatus.DEAD_LETTER):
            return job
        await asyncio.sleep(poll_interval_seconds)


async def _research_online(
    sessionmaker: async_sessionmaker[AsyncSession],
    search_provider: SearchProvider,
    settings: Settings,
    *,
    query: str,
    limit: int,
    refresh: bool,
    execution_mode: ExecutionMode,
    hints: WeatherHint | None = None,
) -> ResearchResponse:
    # `search_provider` is typed as the narrow 2-arg SearchProvider Protocol,
    # but is only ever `CompositeSearchProvider` (which accepts `hints=`) when
    # settings.search_provider == "composite" — calling `hints=` unconditionally
    # would break the `searxng`-only default (SearXNGSearchProvider.search has
    # no `hints` param at all).
    if hints is not None and isinstance(search_provider, CompositeSearchProvider):
        search_results = await search_provider.search(query, limit, hints=hints)
    else:
        search_results = await search_provider.search(query, limit)

    documents: list[ResearchDocument | None] = []
    # (index into documents, search_result, normalized_url, job) for anything not yet resolved
    awaiting: list[tuple[int, SearchResult, str, object]] = []
    now = datetime.now(UTC)

    # Scoped tightly on purpose: blocking mode can wait minutes on the jobs
    # created below, and this session must not sit idle in the pool for that
    # long — it's closed before we ever await a job.
    async with sessionmaker() as session:
        for search_result in search_results:
            if search_result.source == "weather":
                # Answered inline by the provider itself (a forecast lookup,
                # not a webpage) — skip the cache-lookup/crawl-job pipeline
                # entirely, and don't persist it: a forecast should be
                # re-fetched fresh every call, not served stale from the
                # documents cache as the target date approaches.
                documents.append(
                    ResearchDocument(
                        url=search_result.url,
                        normalized_url=normalize_url(search_result.url),
                        title=search_result.title,
                        summary=search_result.snippet,
                        status=ResearchDocumentStatus.COMPUTED,
                        search_rank=search_result.rank,
                    )
                )
                continue
            normalized = normalize_url(search_result.url)
            existing = (
                None
                if refresh
                else await document_repository.get_by_normalized_url(session, normalized)
            )

            if existing is not None and existing.expires_at > now:
                documents.append(
                    _cached_or_crawled_document(
                        search_result, existing, ResearchDocumentStatus.CACHED
                    )
                )
                continue

            # Reuse an in-flight job for this URL rather than creating a
            # duplicate — otherwise polling /v1/research for a URL that
            # hasn't resolved yet (the documented background-mode pattern,
            # ARCHITECTURE.md §5.2) spawns a fresh job on every call.
            job = await crawl_job_repository.get_active_by_url(session, search_result.url)
            if job is None:
                job_type = JobType.REFRESH if existing is not None else JobType.CRAWL
                job = await crawl_job_repository.create(
                    session,
                    type_=job_type,
                    url=search_result.url,
                    max_attempts=settings.job_max_attempts,
                )

            if existing is not None:
                # Stale, not missing — ARCHITECTURE.md §6.2: never block on a
                # refresh, return what we have while it refreshes in the background.
                documents.append(
                    _cached_or_crawled_document(
                        search_result, existing, ResearchDocumentStatus.CACHED
                    )
                )
                continue

            # Truly missing — only this case can make the caller wait (blocking mode).
            documents.append(None)
            awaiting.append((len(documents) - 1, search_result, normalized, job))

    if awaiting and execution_mode == ExecutionMode.BLOCKING:
        finished_jobs = await asyncio.gather(
            *(
                _poll_until_terminal(sessionmaker, job.id, settings.worker_poll_interval_seconds)
                for _, _, _, job in awaiting
            )
        )
        for (idx, search_result, normalized, _job), finished_job in zip(
            awaiting, finished_jobs, strict=True
        ):
            if finished_job.status == JobStatus.COMPLETED:
                async with sessionmaker() as poll_session:
                    doc = await document_repository.get_by_id(
                        poll_session, finished_job.document_id
                    )
                documents[idx] = _cached_or_crawled_document(
                    search_result, doc, ResearchDocumentStatus.CRAWLED
                )
            else:
                documents[idx] = _failed_document(search_result, normalized, finished_job.error)
    elif awaiting:
        for idx, search_result, normalized, job in awaiting:
            documents[idx] = _pending_document(search_result, normalized, job.id)

    resolved_documents = [d for d in documents if d is not None]
    counts = {status: 0 for status in ResearchDocumentStatus}
    for doc in resolved_documents:
        counts[doc.status] += 1

    if execution_mode == ExecutionMode.BLOCKING:
        has_failures = counts[ResearchDocumentStatus.FAILED] > 0
        status = ResearchStatus.COMPLETE_WITH_FAILURES if has_failures else ResearchStatus.COMPLETE
    else:
        has_pending = counts[ResearchDocumentStatus.PENDING] > 0
        status = ResearchStatus.PARTIAL if has_pending else ResearchStatus.COMPLETE

    return ResearchResponse(
        query=query,
        execution_mode=execution_mode,
        status=status,
        cached=counts[ResearchDocumentStatus.CACHED],
        crawled=counts[ResearchDocumentStatus.CRAWLED],
        pending=counts[ResearchDocumentStatus.PENDING],
        failed=counts[ResearchDocumentStatus.FAILED],
        computed=counts[ResearchDocumentStatus.COMPUTED],
        documents=resolved_documents,
    )


async def _research_local(
    session: AsyncSession, execution_mode: ExecutionMode, *, query: str, limit: int
) -> ResearchResponse:
    docs = await search_local(session, query, limit)
    documents = [
        _cached_or_crawled_document(None, doc, ResearchDocumentStatus.CACHED) for doc in docs
    ]
    return ResearchResponse(
        query=query,
        execution_mode=execution_mode,
        status=ResearchStatus.COMPLETE,
        cached=len(documents),
        documents=documents,
    )


async def research(
    sessionmaker: async_sessionmaker[AsyncSession],
    search_provider: SearchProvider,
    settings: Settings,
    *,
    query: str,
    limit: int,
    refresh: bool,
    execution_mode: ExecutionMode,
    mode: RetrievalMode,
    hints: WeatherHint | None = None,
) -> ResearchResponse:
    """Orchestrates search + cache lookup + crawl + merge. ARCHITECTURE.md §5."""
    if mode == RetrievalMode.SEMANTIC:
        raise SemanticSearchNotImplementedError

    if mode == RetrievalMode.LOCAL:
        async with sessionmaker() as session:
            return await _research_local(session, execution_mode, query=query, limit=limit)

    return await _research_online(
        sessionmaker,
        search_provider,
        settings,
        query=query,
        limit=limit,
        refresh=refresh,
        execution_mode=execution_mode,
        hints=hints,
    )
