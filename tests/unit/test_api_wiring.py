"""End-to-end wiring smoke test: does a request actually flow
auth -> router -> research service -> response, with real dependency
overrides rather than a live Postgres/SearXNG. Full DB-backed behavior is
covered by integration tests (BUILD.md §5) once the compose stack exists.
"""

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.api.deps import get_research_sessionmaker, get_search_provider_dep, require_api_key
from app.config import ExecutionMode, get_settings
from app.database import get_db_session
from app.models import ApiKey, ApiKeyStatus
from app.repositories import api_key_repository
from app.schemas.research import RetrievalMode
from app.services.search.provider import SearchResult
from main import app


async def _fake_db_session():
    yield None


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


def test_admin_api_rejects_when_secret_unconfigured(settings):
    app.dependency_overrides[get_settings] = lambda: settings  # admin_api_secret == ""
    try:
        client = TestClient(app)
        response = client.get("/admin/api-keys", headers={"Authorization": "Bearer anything"})
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "UNAUTHORIZED"
    finally:
        app.dependency_overrides.clear()


def test_admin_api_rejects_wrong_secret(settings):
    configured = settings.model_copy(update={"admin_api_secret": "correct-secret"})
    app.dependency_overrides[get_settings] = lambda: configured
    try:
        client = TestClient(app)
        response = client.get("/admin/api-keys", headers={"Authorization": "Bearer wrong"})
        assert response.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_admin_api_key_lifecycle_create_list_disable_delete(settings, monkeypatch):
    """Create -> the raw key is only ever in the create response. List/get
    never expose it or the hash. Disable flips status without deleting.
    Delete removes it; get then 404s."""
    store: dict[uuid.UUID, ApiKey] = {}

    async def fake_create(session, *, key_hash, label, rate_limit_per_minute, expires_at):
        key = ApiKey(
            key_hash=key_hash,
            label=label,
            rate_limit_per_minute=rate_limit_per_minute,
            expires_at=expires_at,
            status=ApiKeyStatus.ACTIVE,
        )
        key.id = uuid.uuid4()
        key.created_at = datetime.now(UTC)
        key.updated_at = datetime.now(UTC)
        store[key.id] = key
        return key

    async def fake_list_all(session):
        return list(store.values())

    async def fake_get_by_id(session, key_id):
        return store.get(key_id)

    async def fake_update_status(session, api_key, status):
        api_key.status = status
        return api_key

    async def fake_delete(session, api_key):
        del store[api_key.id]

    monkeypatch.setattr(api_key_repository, "create", fake_create)
    monkeypatch.setattr(api_key_repository, "list_all", fake_list_all)
    monkeypatch.setattr(api_key_repository, "get_by_id", fake_get_by_id)
    monkeypatch.setattr(api_key_repository, "update_status", fake_update_status)
    monkeypatch.setattr(api_key_repository, "delete", fake_delete)

    configured = settings.model_copy(update={"admin_api_secret": "correct-secret"})
    app.dependency_overrides[get_settings] = lambda: configured
    app.dependency_overrides[get_db_session] = _fake_db_session
    headers = {"Authorization": "Bearer correct-secret"}

    try:
        client = TestClient(app)

        created = client.post("/admin/api-keys", json={"label": "ops-key"}, headers=headers)
        assert created.status_code == 201
        body = created.json()
        assert "raw_key" in body and len(body["raw_key"]) > 20
        assert body["status"] == "active"
        assert body["expires_at"] is None
        key_id = body["id"]

        listed = client.get("/admin/api-keys", headers=headers)
        assert listed.status_code == 200
        assert "raw_key" not in listed.json()[0]
        assert "key_hash" not in listed.json()[0]

        disabled = client.patch(
            f"/admin/api-keys/{key_id}", json={"status": "disabled"}, headers=headers
        )
        assert disabled.status_code == 200
        assert disabled.json()["status"] == "disabled"

        deleted = client.delete(f"/admin/api-keys/{key_id}", headers=headers)
        assert deleted.status_code == 204

        missing = client.get(f"/admin/api-keys/{key_id}", headers=headers)
        assert missing.status_code == 404
    finally:
        app.dependency_overrides.clear()
