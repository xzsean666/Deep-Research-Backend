"""End-to-end wiring smoke test: does a request actually flow
auth -> router -> research service -> response, with real dependency
overrides rather than a live Postgres/SearXNG. Full DB-backed behavior is
covered by integration tests (BUILD.md §5) once the compose stack exists.
"""

from fastapi.testclient import TestClient

from app.api.deps import get_research_sessionmaker, get_search_provider_dep, require_api_key
from app.config import ExecutionMode, get_settings
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

    async def fake_get_active_by_url(session, url):
        return None  # no in-flight job yet

    async def fake_create(session, *, type_, url, max_attempts):
        return type("FakeJob", (), {"id": uuid.uuid4()})()

    monkeypatch.setattr(document_repository, "get_by_normalized_url", fake_get_by_normalized_url)
    monkeypatch.setattr(crawl_job_repository, "get_active_by_url", fake_get_active_by_url)
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


def test_require_api_key_false_allows_requests_with_no_authorization_header(
    monkeypatch, settings
):
    """REQUIRE_API_KEY=false — for a network-isolated deployment — must
    let a request through with no Authorization header at all, exercising
    the real require_api_key dependency (not overridden away), only
    get_settings is swapped for one with require_api_key=False.
    """
    from app.repositories import crawl_job_repository, document_repository

    async def fake_get_by_normalized_url(session, normalized_url):
        return None

    async def fake_get_active_by_url(session, url):
        return None

    async def fake_create(session, *, type_, url, max_attempts):
        import uuid

        return type("FakeJob", (), {"id": uuid.uuid4()})()

    monkeypatch.setattr(document_repository, "get_by_normalized_url", fake_get_by_normalized_url)
    monkeypatch.setattr(crawl_job_repository, "get_active_by_url", fake_get_active_by_url)
    monkeypatch.setattr(crawl_job_repository, "create", fake_create)

    open_settings = settings.model_copy(update={"require_api_key": False})
    app.dependency_overrides[get_settings] = lambda: open_settings
    app.dependency_overrides[get_research_sessionmaker] = lambda: _fake_sessionmaker
    app.dependency_overrides[get_search_provider_dep] = lambda: _FakeSearchProvider()

    try:
        client = TestClient(app)
        response = client.post(
            "/v1/research",
            json={"query": "hello", "execution_mode": ExecutionMode.BACKGROUND.value},
        )
        assert response.status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_semantic_mode_returns_clean_501_not_a_raw_500():
    """Caught in production: mode='semantic' crashed with an unhandled
    500 instead of a structured error, because SemanticSearchNotImplementedError
    had no registered exception handler. See app/api/errors.py.
    """
    app.dependency_overrides[require_api_key] = lambda: ApiKey(
        key_hash="x", label="test", rate_limit_per_minute=60
    )
    app.dependency_overrides[get_research_sessionmaker] = lambda: _fake_sessionmaker
    app.dependency_overrides[get_search_provider_dep] = lambda: _FakeSearchProvider()

    try:
        client = TestClient(app)
        response = client.post(
            "/v1/research",
            json={"query": "hello", "mode": RetrievalMode.SEMANTIC.value},
        )
        assert response.status_code == 501
        assert response.json()["error"]["code"] == "NOT_IMPLEMENTED"
    finally:
        app.dependency_overrides.clear()
