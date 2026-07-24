"""Contract test for TruthSocialSearchProvider.

Uses a recorded fixture response via httpx.MockTransport rather than a live
Truth Social endpoint, so it runs in any environment; it still exercises
the exact parsing code the real HTTP call goes through.
"""

import httpx

from app.services.search.truth_social_provider import TruthSocialSearchProvider

# Trimmed shape of a real Truth Social `/api/v2/search?type=statuses` response.
_FIXTURE_RESPONSE = {
    "statuses": [
        {
            "id": "112233",
            "url": "https://truthsocial.com/@realDonaldTrump/112233",
            "content": "<p>Big statement about the <b>economy</b>!</p>",
            "created_at": "2026-07-15T17:01:12.000Z",
            "account": {"acct": "realDonaldTrump", "display_name": "Donald J. Trump"},
        },
        {
            # No url/uri, but acct+id present — URL must be constructed.
            "id": "445566",
            "content": "Another post with no direct url field",
            "account": {"acct": "realDonaldTrump"},
        },
        {
            # No usable url at all — must be skipped.
            "id": None,
            "content": "Orphaned content",
            "account": {},
        },
        {
            # A reblog wrapper — the inner reblog should be unwrapped.
            "reblog": {
                "id": "778899",
                "url": "https://truthsocial.com/@someoneelse/778899",
                "content": "Reblogged content",
                "account": {"acct": "someoneelse"},
            }
        },
    ]
}


def _mock_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v2/search"
        assert request.url.params["q"] == "economy"
        assert request.url.params["type"] == "statuses"
        return httpx.Response(200, json=_FIXTURE_RESPONSE)

    return httpx.MockTransport(handler)


async def test_maps_truth_social_response_to_search_result():
    client = httpx.AsyncClient(transport=_mock_transport())
    provider = TruthSocialSearchProvider(base_url="https://truthsocial.test", client=client)

    results = await provider.search("economy", limit=10)

    assert len(results) == 3
    assert results[0].url == "https://truthsocial.com/@realDonaldTrump/112233"
    assert results[0].title == "Big statement about the economy !"
    assert results[0].snippet == "Big statement about the economy !"


async def test_constructs_url_when_missing():
    client = httpx.AsyncClient(transport=_mock_transport())
    provider = TruthSocialSearchProvider(base_url="https://truthsocial.test", client=client)

    results = await provider.search("economy", limit=10)

    assert results[1].url == "https://truthsocial.com/@realDonaldTrump/445566"


async def test_unwraps_reblog():
    client = httpx.AsyncClient(transport=_mock_transport())
    provider = TruthSocialSearchProvider(base_url="https://truthsocial.test", client=client)

    results = await provider.search("economy", limit=10)

    assert results[2].url == "https://truthsocial.com/@someoneelse/778899"
    assert results[2].snippet == "Reblogged content"


async def test_respects_limit():
    client = httpx.AsyncClient(transport=_mock_transport())
    provider = TruthSocialSearchProvider(base_url="https://truthsocial.test", client=client)

    results = await provider.search("economy", limit=1)

    assert len(results) == 1


_FACTBASE_FIXTURE = {
    "data": [
        {
            "platform": "Truth Social",
            "date": "2026-07-15T18:54:07-04:00",
            "text": "Iran has allowed an American Citizen to leave",
            "post_url": "https://truthsocial.com/@realDonaldTrump/998877",
        },
        {
            # Different platform — must be filtered out.
            "platform": "Twitter",
            "text": "Some tweet",
            "post_url": "https://x.com/realDonaldTrump/1",
        },
        {
            # No usable url — must be skipped.
            "platform": "Truth Social",
            "text": "No url here",
        },
    ]
}


def _falls_back_transport(primary_status: int) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/search":
            if primary_status == 200:
                return httpx.Response(200, json={"statuses": []})
            return httpx.Response(primary_status, json={})
        assert request.url.path == "/wp-json/factbase/v1/twitter"
        assert request.headers["referer"] == "https://rollcall.com/factbase-twitter/"
        return httpx.Response(200, json=_FACTBASE_FIXTURE)

    return httpx.MockTransport(handler)


async def test_falls_back_to_factbase_archive_when_primary_errors():
    client = httpx.AsyncClient(transport=_falls_back_transport(primary_status=403))
    provider = TruthSocialSearchProvider(base_url="https://truthsocial.test", client=client)

    results = await provider.search("iran", limit=10)

    assert len(results) == 1
    assert results[0].url == "https://truthsocial.com/@realDonaldTrump/998877"
    assert results[0].snippet == "Iran has allowed an American Citizen to leave"


async def test_falls_back_to_factbase_archive_when_primary_returns_empty():
    client = httpx.AsyncClient(transport=_falls_back_transport(primary_status=200))
    provider = TruthSocialSearchProvider(base_url="https://truthsocial.test", client=client)

    results = await provider.search("iran", limit=10)

    assert len(results) == 1
    assert results[0].url == "https://truthsocial.com/@realDonaldTrump/998877"


_FACTBASE_OFF_TOPIC_FIXTURE = {
    "data": [
        {
            "platform": "Truth Social",
            "date": "2026-07-15T18:54:07-04:00",
            # Deliberately shares a bare year with the query below (both
            # mention "2026") — this must NOT be enough to count as
            # relevant on its own (see test_ignores_bare_year_overlap).
            "text": "Effective August 1st, 2026, all Generic Drugs being brought into the "
            "United States will continue to have a TARIFF of ZERO PERCENT",
            "post_url": "https://truthsocial.com/@realDonaldTrump/111222",
        },
        {
            "platform": "Truth Social",
            "date": "2026-07-14T10:00:00-04:00",
            "text": "Blame immigration chaos on Biden and Harris, not Trump",
            "post_url": "https://truthsocial.com/@realDonaldTrump/333444",
        },
    ]
}


def _off_topic_fallback_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/search":
            return httpx.Response(200, json={"statuses": []})
        assert request.url.path == "/wp-json/factbase/v1/twitter"
        return httpx.Response(200, json=_FACTBASE_OFF_TOPIC_FIXTURE)

    return httpx.MockTransport(handler)


async def test_factbase_archive_drops_results_unrelated_to_the_query():
    """Regression test: the Factbase archive ignores its own `q` parameter
    and always returns its most recent posts (confirmed live 2026-07-22),
    so a query about something Trump never posted about must come back
    empty rather than silently returning unrelated posts as evidence.
    """
    client = httpx.AsyncClient(transport=_off_topic_fallback_transport())
    provider = TruthSocialSearchProvider(base_url="https://truthsocial.test", client=client)

    results = await provider.search("Ankara highest temperature July 23", limit=10)

    assert results == []


async def test_ignores_bare_year_overlap():
    """Regression test: a shared bare year (e.g. "2026") must not count as
    relevance on its own — confirmed live, this exact query matched the
    exact fixture text above via the year alone before this was excluded,
    since almost every post and every market question is dated 2026.
    """
    client = httpx.AsyncClient(transport=_off_topic_fallback_transport())
    provider = TruthSocialSearchProvider(base_url="https://truthsocial.test", client=client)

    results = await provider.search("Ankara highest temperature July 23 2026", limit=10)

    assert results == []


_FACTBASE_SINGLE_WORD_COINCIDENCE_FIXTURE = {
    "data": [
        {
            "platform": "Truth Social",
            "date": "2026-07-05T12:00:00-04:00",
            # Shares only the word "july" with the query below — a second
            # live failure after the bare-year one: "july" alone isn't rare
            # enough to mean these are about the same thing.
            "text": "We got it through the great July Fourth Weekend. What kind of "
            "animals would do such a thing to the Reflecting Pool?",
            "post_url": "https://truthsocial.com/@realDonaldTrump/555666",
        },
    ]
}


def _single_word_coincidence_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/search":
            return httpx.Response(200, json={"statuses": []})
        assert request.url.path == "/wp-json/factbase/v1/twitter"
        return httpx.Response(200, json=_FACTBASE_SINGLE_WORD_COINCIDENCE_FIXTURE)

    return httpx.MockTransport(handler)


async def test_ignores_single_generic_word_coincidence():
    """Regression test: confirmed live 2026-07-22, "Ankara highest
    temperature July 23 2026" matched an unrelated Reflecting-Pool post
    purely because both mention "july" — a single shared calendar word
    isn't enough for a query with several other, unmatched tokens.
    """
    client = httpx.AsyncClient(transport=_single_word_coincidence_transport())
    provider = TruthSocialSearchProvider(base_url="https://truthsocial.test", client=client)

    results = await provider.search("Ankara highest temperature July 23 2026", limit=10)

    assert results == []


async def test_factbase_archive_keeps_results_relevant_to_the_query():
    client = httpx.AsyncClient(transport=_off_topic_fallback_transport())
    provider = TruthSocialSearchProvider(base_url="https://truthsocial.test", client=client)

    results = await provider.search("generic drugs tariff", limit=10)

    assert len(results) == 1
    assert results[0].url == "https://truthsocial.com/@realDonaldTrump/111222"


def test_passes_proxy_to_default_client(monkeypatch):
    seen_kwargs = {}

    class _FakeAsyncClient:
        def __init__(self, **kwargs):
            seen_kwargs.update(kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    TruthSocialSearchProvider(proxy="http://proxy.test:8080")

    assert seen_kwargs["proxy"] == "http://proxy.test:8080"
