import uuid
from dataclasses import dataclass

from app.repositories import crawl_job_repository, document_repository
from app.services.crawl.errors import CrawlBlockedError, CrawlFetchError
from app.services.crawl.provider import CrawlResult
from app.services.worker.loop import process_one_job


@dataclass
class FakeJob:
    id: uuid.UUID
    url: str


class FakeCrawlProviderSuccess:
    async def crawl(self, url):
        return CrawlResult(url=url, title="T", markdown="hello world", metadata={"k": "v"})


class FakeCrawlProviderBlocked:
    async def crawl(self, url):
        raise CrawlBlockedError(url, "blocked")


class FakeCrawlProviderFetchError:
    async def crawl(self, url):
        raise CrawlFetchError(url, "timeout")


async def test_returns_false_when_nothing_to_claim(monkeypatch, settings):
    async def fake_claim_next(session):
        return None

    monkeypatch.setattr(crawl_job_repository, "claim_next", fake_claim_next)

    claimed = await process_one_job(None, FakeCrawlProviderSuccess(), settings)

    assert claimed is False


async def test_success_path_upserts_document_and_completes_job(monkeypatch, settings):
    job = FakeJob(id=uuid.uuid4(), url="https://docs.python.org/3/")
    calls = {}

    async def fake_claim_next(session):
        return job

    async def fake_upsert(session, **kwargs):
        calls["upsert_kwargs"] = kwargs
        return type("Doc", (), {"id": uuid.uuid4()})()

    async def fake_mark_completed(session, job_id, document_id):
        calls["completed"] = (job_id, document_id)

    monkeypatch.setattr(crawl_job_repository, "claim_next", fake_claim_next)
    monkeypatch.setattr(document_repository, "upsert", fake_upsert)
    monkeypatch.setattr(crawl_job_repository, "mark_completed", fake_mark_completed)

    claimed = await process_one_job(None, FakeCrawlProviderSuccess(), settings)

    assert claimed is True
    assert calls["upsert_kwargs"]["markdown"] == "hello world"
    assert calls["completed"][0] == job.id


async def test_blocked_url_is_marked_permanent_failure(monkeypatch, settings):
    job = FakeJob(id=uuid.uuid4(), url="http://internal.example.com/")
    calls = {}

    async def fake_claim_next(session):
        return job

    async def fake_mark_failed(session, job_id, error, permanent=False):
        calls["args"] = (job_id, error, permanent)

    monkeypatch.setattr(crawl_job_repository, "claim_next", fake_claim_next)
    monkeypatch.setattr(crawl_job_repository, "mark_failed", fake_mark_failed)

    claimed = await process_one_job(None, FakeCrawlProviderBlocked(), settings)

    assert claimed is True
    assert calls["args"][2] is True  # permanent — never retried


async def test_fetch_error_is_marked_retryable_failure(monkeypatch, settings):
    job = FakeJob(id=uuid.uuid4(), url="https://example.com/")
    calls = {}

    async def fake_claim_next(session):
        return job

    async def fake_mark_failed(session, job_id, error, permanent=False):
        calls["args"] = (job_id, error, permanent)

    monkeypatch.setattr(crawl_job_repository, "claim_next", fake_claim_next)
    monkeypatch.setattr(crawl_job_repository, "mark_failed", fake_mark_failed)

    claimed = await process_one_job(None, FakeCrawlProviderFetchError(), settings)

    assert claimed is True
    assert calls["args"][2] is False  # retryable, not permanent
