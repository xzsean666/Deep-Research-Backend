import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.config import ExecutionMode
from app.models import Document, JobStatus, SourceType
from app.repositories import crawl_job_repository, document_repository
from app.schemas.research import ResearchDocumentStatus, ResearchStatus, RetrievalMode
from app.services.research import SemanticSearchNotImplementedError, research
from app.services.research import research_service as research_service_module
from app.services.search.provider import SearchResult


class FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


def fake_sessionmaker():
    return FakeSession()


class FakeSearchProvider:
    def __init__(self, results):
        self._results = results

    async def search(self, query, limit):
        return self._results[:limit]


def make_document(**overrides):
    now = datetime.now(UTC)
    defaults = {
        "id": uuid.uuid4(),
        "url": "https://example.com/a",
        "normalized_url": "example.com/a",
        "title": "Title",
        "markdown": "hello world",
        "summary": "hello world",
        "source_type": SourceType.BLOG,
        "doc_metadata": {},
        "fetched_at": now,
        "expires_at": now + timedelta(days=1),
    }
    defaults.update(overrides)
    return Document(**defaults)


async def test_online_cached_and_fresh_never_creates_a_job(monkeypatch, settings):
    doc = make_document()

    async def fake_get_by_normalized_url(session, normalized_url):
        return doc

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("must not create a job for a cached, fresh document")

    monkeypatch.setattr(document_repository, "get_by_normalized_url", fake_get_by_normalized_url)
    monkeypatch.setattr(crawl_job_repository, "create", fail_if_called)

    search_provider = FakeSearchProvider(
        [SearchResult(url="https://example.com/a", title="t", snippet="s", rank=1)]
    )

    response = await research(
        fake_sessionmaker,
        search_provider,
        settings,
        query="q",
        limit=5,
        refresh=False,
        execution_mode=ExecutionMode.BLOCKING,
        mode=RetrievalMode.ONLINE,
    )

    assert response.status == ResearchStatus.COMPLETE
    assert response.cached == 1
    assert response.documents[0].status == ResearchDocumentStatus.CACHED


async def test_online_missing_document_blocking_waits_for_job_completion(monkeypatch, settings):
    job_id = uuid.uuid4()
    document_id = uuid.uuid4()
    crawled_doc = make_document(id=document_id, markdown="crawled content")

    async def fake_get_by_normalized_url(session, normalized_url):
        return None

    async def fake_create(session, *, type_, url, max_attempts):
        return type("FakeJob", (), {"id": job_id})()

    async def fake_get_by_id_job(session, job_id_arg):
        return type(
            "FakeJob",
            (),
            {"status": JobStatus.COMPLETED, "document_id": document_id, "error": None},
        )()

    async def fake_get_by_id_doc(session, doc_id):
        return crawled_doc

    monkeypatch.setattr(document_repository, "get_by_normalized_url", fake_get_by_normalized_url)
    monkeypatch.setattr(crawl_job_repository, "create", fake_create)
    monkeypatch.setattr(crawl_job_repository, "get_by_id", fake_get_by_id_job)
    monkeypatch.setattr(document_repository, "get_by_id", fake_get_by_id_doc)

    search_provider = FakeSearchProvider(
        [SearchResult(url="https://new.example.com/", title="t", snippet="s", rank=1)]
    )

    response = await research(
        fake_sessionmaker,
        search_provider,
        settings,
        query="q",
        limit=5,
        refresh=False,
        execution_mode=ExecutionMode.BLOCKING,
        mode=RetrievalMode.ONLINE,
    )

    assert response.status == ResearchStatus.COMPLETE
    assert response.crawled == 1
    assert response.documents[0].status == ResearchDocumentStatus.CRAWLED


async def test_online_missing_document_blocking_reports_failure_on_dead_letter(
    monkeypatch, settings
):
    job_id = uuid.uuid4()

    async def fake_get_by_normalized_url(session, normalized_url):
        return None

    async def fake_create(session, *, type_, url, max_attempts):
        return type("FakeJob", (), {"id": job_id})()

    async def fake_get_by_id_job(session, job_id_arg):
        return type(
            "FakeJob",
            (),
            {"status": JobStatus.DEAD_LETTER, "document_id": None, "error": "404 not found"},
        )()

    monkeypatch.setattr(document_repository, "get_by_normalized_url", fake_get_by_normalized_url)
    monkeypatch.setattr(crawl_job_repository, "create", fake_create)
    monkeypatch.setattr(crawl_job_repository, "get_by_id", fake_get_by_id_job)

    search_provider = FakeSearchProvider(
        [SearchResult(url="https://gone.example.com/", title="t", snippet="s", rank=1)]
    )

    response = await research(
        fake_sessionmaker,
        search_provider,
        settings,
        query="q",
        limit=5,
        refresh=False,
        execution_mode=ExecutionMode.BLOCKING,
        mode=RetrievalMode.ONLINE,
    )

    assert response.status == ResearchStatus.COMPLETE_WITH_FAILURES
    assert response.failed == 1
    assert response.documents[0].error == "404 not found"


async def test_online_missing_document_background_returns_pending_immediately(
    monkeypatch, settings
):
    job_id = uuid.uuid4()

    async def fake_get_by_normalized_url(session, normalized_url):
        return None

    async def fake_create(session, *, type_, url, max_attempts):
        return type("FakeJob", (), {"id": job_id})()

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("background mode must never poll a job")

    monkeypatch.setattr(document_repository, "get_by_normalized_url", fake_get_by_normalized_url)
    monkeypatch.setattr(crawl_job_repository, "create", fake_create)
    monkeypatch.setattr(crawl_job_repository, "get_by_id", fail_if_called)

    search_provider = FakeSearchProvider(
        [SearchResult(url="https://new.example.com/", title="t", snippet="s", rank=1)]
    )

    response = await research(
        fake_sessionmaker,
        search_provider,
        settings,
        query="q",
        limit=5,
        refresh=False,
        execution_mode=ExecutionMode.BACKGROUND,
        mode=RetrievalMode.ONLINE,
    )

    assert response.status == ResearchStatus.PARTIAL
    assert response.pending == 1
    assert response.documents[0].status == ResearchDocumentStatus.PENDING
    assert response.documents[0].job_id == job_id


async def test_refresh_flag_forces_recrawl_of_a_fresh_cached_document(monkeypatch, settings):
    doc = make_document()  # fresh, would normally short-circuit to cached
    job_id = uuid.uuid4()

    async def fake_get_by_normalized_url(session, normalized_url):
        return doc

    async def fake_create(session, *, type_, url, max_attempts):
        return type("FakeJob", (), {"id": job_id})()

    monkeypatch.setattr(document_repository, "get_by_normalized_url", fake_get_by_normalized_url)
    monkeypatch.setattr(crawl_job_repository, "create", fake_create)

    search_provider = FakeSearchProvider(
        [SearchResult(url="https://example.com/a", title="t", snippet="s", rank=1)]
    )

    response = await research(
        fake_sessionmaker,
        search_provider,
        settings,
        query="q",
        limit=5,
        refresh=True,
        execution_mode=ExecutionMode.BACKGROUND,
        mode=RetrievalMode.ONLINE,
    )

    assert response.documents[0].status == ResearchDocumentStatus.PENDING


async def test_semantic_mode_is_not_implemented(settings):
    with pytest.raises(SemanticSearchNotImplementedError):
        await research(
            fake_sessionmaker,
            FakeSearchProvider([]),
            settings,
            query="q",
            limit=5,
            refresh=False,
            execution_mode=ExecutionMode.BLOCKING,
            mode=RetrievalMode.SEMANTIC,
        )


async def test_local_mode_returns_already_cached_documents(monkeypatch, settings):
    doc = make_document()

    async def fake_search_local(session, query, limit):
        return [doc]

    monkeypatch.setattr(research_service_module, "search_local", fake_search_local)

    response = await research(
        fake_sessionmaker,
        FakeSearchProvider([]),
        settings,
        query="q",
        limit=5,
        refresh=False,
        execution_mode=ExecutionMode.BLOCKING,
        mode=RetrievalMode.LOCAL,
    )

    assert response.status == ResearchStatus.COMPLETE
    assert response.cached == 1
    assert response.documents[0].status == ResearchDocumentStatus.CACHED
