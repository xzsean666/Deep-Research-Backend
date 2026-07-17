"""End-to-end wiring smoke test: does a request actually flow
auth -> router -> research service -> response, with real dependency
overrides rather than a live Postgres/SearXNG. Full DB-backed behavior is
covered by integration tests (BUILD.md §5) once the compose stack exists.
"""

from fastapi.testclient import TestClient

from app.api.deps import get_research_sessionmaker, get_search_provider_dep, require_api_key
from app.config import ExecutionMode
from app.models import ApiKey
from app.schemas.research import RetrievalMode
from app.services.search.provider import SearchResult
from main import app


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


def _fake_sessionmaker():
    return _FakeSession()


class _FakeSearchProvider:
    async def search(self, query, limit):
        return [SearchResult(url="https://example.com/a", title="A", snippet="s", rank=1)]


def test_research_endpoint_requires_auth():
    client = TestClient(app)
    response = client.post("/v1/research", json={"query": "hello"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_research_endpoint_end_to_end_with_overrides(monkeypatch):
    import uuid

    from app.repositories import crawl_job_repository, document_repository

    async def fake_get_by_normalized_url(session, normalized_url):
        return None  # forces the "missing document" path

    async def fake_create(session, *, type_, url, max_attempts):
        return type("FakeJob", (), {"id": uuid.uuid4()})()

    monkeypatch.setattr(document_repository, "get_by_normalized_url", fake_get_by_normalized_url)
    monkeypatch.setattr(crawl_job_repository, "create", fake_create)

    app.dependency_overrides[require_api_key] = lambda: ApiKey(
        key_hash="x", label="test", rate_limit_per_minute=60
    )
    app.dependency_overrides[get_research_sessionmaker] = lambda: _fake_sessionmaker
    app.dependency_overrides[get_search_provider_dep] = lambda: _FakeSearchProvider()

    try:
        client = TestClient(app)
        response = client.post(
            "/v1/research",
            json={
                "query": "hello",
                "execution_mode": ExecutionMode.BACKGROUND.value,
                "mode": RetrievalMode.ONLINE.value,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "partial"
        assert body["pending"] == 1
        assert body["documents"][0]["status"] == "pending"
    finally:
        app.dependency_overrides.clear()
