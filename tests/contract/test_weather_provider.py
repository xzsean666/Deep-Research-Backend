"""Contract test for WeatherSearchProvider.

Uses httpx.MockTransport for both Open-Meteo hosts (geocoding + forecast)
rather than live calls, so it runs in any environment.
"""

from datetime import datetime, timezone

import httpx

from app.schemas.research import WeatherExtremum, WeatherHint
from app.services.search.weather_provider import WeatherSearchProvider

_GEOCODING_HOST = "geocoding-api.open-meteo.test"
_FORECAST_HOST = "api.open-meteo.test"


def _hint(**overrides) -> WeatherHint:
    defaults = dict(
        city="Seoul",
        market_end_date_utc=datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc),
        extremum=WeatherExtremum.HIGHEST,
        threshold_celsius=29.0,
    )
    defaults.update(overrides)
    return WeatherHint(**defaults)


def _provider(handler) -> WeatherSearchProvider:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return WeatherSearchProvider(
        geocoding_base_url=f"https://{_GEOCODING_HOST}",
        forecast_base_url=f"https://{_FORECAST_HOST}",
        client=client,
    )


def _happy_path_handler(daily_field_expected: str = "temperature_2m_max"):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == _GEOCODING_HOST:
            assert request.url.params["name"] == "Seoul"
            return httpx.Response(
                200,
                json={"results": [{"latitude": 37.57, "longitude": 126.98}]},
            )
        assert request.url.host == _FORECAST_HOST
        assert request.url.params["daily"] == daily_field_expected
        assert request.url.params["start_date"] == "2026-07-22"
        assert request.url.params["end_date"] == "2026-07-22"
        assert request.url.params["temperature_unit"] == "celsius"
        return httpx.Response(200, json={"daily": {daily_field_expected: [28.7]}})

    return handler


async def test_returns_empty_when_hints_missing():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={})

    provider = _provider(handler)

    results = await provider.search("some unrelated query", limit=5, hints=None)

    assert results == []
    assert calls == []


async def test_geocodes_then_fetches_forecast_and_builds_result():
    provider = _provider(_happy_path_handler())

    results = await provider.search("Seoul temperature forecast", limit=5, hints=_hint())

    assert len(results) == 1
    result = results[0]
    assert result.url.startswith(f"https://{_FORECAST_HOST}/v1/forecast")
    assert "28.7" in result.snippet
    assert "29.0" in result.snippet
    assert "below" in result.snippet
    assert "Seoul" in result.title


async def test_returns_empty_when_geocoding_finds_no_city():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == _GEOCODING_HOST
        return httpx.Response(200, json={"results": []})

    provider = _provider(handler)

    results = await provider.search("query", limit=5, hints=_hint())

    assert results == []


async def test_selects_min_field_for_lowest_extremum():
    provider = _provider(_happy_path_handler(daily_field_expected="temperature_2m_min"))

    results = await provider.search(
        "query", limit=5, hints=_hint(extremum=WeatherExtremum.LOWEST)
    )

    assert len(results) == 1
    assert "lowest" in results[0].snippet


async def test_forecast_at_or_above_threshold_reads_as_such():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == _GEOCODING_HOST:
            return httpx.Response(
                200, json={"results": [{"latitude": 37.57, "longitude": 126.98}]}
            )
        return httpx.Response(200, json={"daily": {"temperature_2m_max": [31.2]}})

    provider = _provider(handler)

    results = await provider.search("query", limit=5, hints=_hint())

    assert "at or above" in results[0].snippet


def test_passes_proxy_to_default_client(monkeypatch):
    seen_kwargs = {}

    class _FakeAsyncClient:
        def __init__(self, **kwargs):
            seen_kwargs.update(kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    WeatherSearchProvider(proxy="http://proxy.test:8080")

    assert seen_kwargs["proxy"] == "http://proxy.test:8080"
