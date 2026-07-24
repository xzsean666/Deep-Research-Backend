import httpx

from app.schemas.research import WeatherExtremum, WeatherHint
from app.services.search.provider import SearchResult


class WeatherSearchProvider:
    """Free, no-API-key weather forecast source for weather-bracket markets
    (Open-Meteo: https://open-meteo.com, 10,000 free calls/day, no auth).

    Two Open-Meteo hosts are involved — geocoding (city name -> lat/lon) and
    forecast (lat/lon/date -> daily max/min temperature) — both called
    through the same injected client, since neither call relies on the
    client's own base_url (both build absolute URLs from the two configured
    base URLs).

    Only ever meaningful when `hints` is supplied: the calling trading bot
    already knows (via Polymarket's own Gamma tag, not a text guess) that a
    market is a weather bracket, and has parsed city/extremum/threshold from
    its verbatim question text plus its authoritative end_date. Without
    `hints`, this returns [] immediately rather than trying to guess a
    city/date from the free-text `query` — that text is an LLM keyword
    extraction with no guaranteed structure to parse.
    """

    def __init__(
        self,
        geocoding_base_url: str = "https://geocoding-api.open-meteo.com",
        forecast_base_url: str = "https://api.open-meteo.com",
        proxy: str | None = None,
        client: httpx.AsyncClient | None = None,
    ):
        self._geocoding_base_url = geocoding_base_url.rstrip("/")
        self._forecast_base_url = forecast_base_url.rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=10, proxy=proxy)

    async def search(
        self, query: str, limit: int, hints: WeatherHint | None = None
    ) -> list[SearchResult]:
        if hints is None:
            return []

        geo_response = await self._client.get(
            f"{self._geocoding_base_url}/v1/search",
            params={"name": hints.city, "count": 1, "language": "en", "format": "json"},
        )
        geo_response.raise_for_status()
        geo_results = geo_response.json().get("results") or []
        if not geo_results:
            return []
        place = geo_results[0]
        latitude, longitude = place["latitude"], place["longitude"]

        # Confirmed live 2026-07-24 across 10+ real weather-bracket markets:
        # `market_end_date_utc` is always exactly
        # "<the question's stated date>T12:00:00Z" UTC — its UTC calendar
        # date IS the target forecast date, no timezone conversion needed.
        target_date = hints.market_end_date_utc.date().isoformat()

        daily_field = (
            "temperature_2m_max"
            if hints.extremum == WeatherExtremum.HIGHEST
            else "temperature_2m_min"
        )
        forecast_url = f"{self._forecast_base_url}/v1/forecast"
        forecast_params = {
            "latitude": latitude,
            "longitude": longitude,
            "daily": daily_field,
            "temperature_unit": "celsius",
            "start_date": target_date,
            "end_date": target_date,
        }
        forecast_response = await self._client.get(forecast_url, params=forecast_params)
        forecast_response.raise_for_status()
        daily = forecast_response.json().get("daily", {})
        values = daily.get(daily_field) or []
        if not values or values[0] is None:
            return []
        forecast_value = values[0]

        full_url = str(httpx.Request("GET", forecast_url, params=forecast_params).url)
        comparison = "at or above" if forecast_value >= hints.threshold_celsius else "below"
        snippet = (
            f"Open-Meteo forecast: {hints.extremum.value} temperature in {hints.city} "
            f"on {target_date} is forecast at {forecast_value}°C, "
            f"{comparison} the market's {hints.threshold_celsius}°C threshold."
        )
        return [
            SearchResult(
                url=full_url,
                title=f"Open-Meteo forecast for {hints.city} on {target_date}",
                snippet=snippet,
                rank=1,
            )
        ]
