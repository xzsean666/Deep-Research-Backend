import asyncio
import dataclasses
import logging
from collections import deque

from app.schemas.research import WeatherHint
from app.services.document import normalize_url
from app.services.search.provider import SearchProvider, SearchResult

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class WeightedSource:
    """One search source plus how much it's trusted relative to the others.

    `max_results` bounds how many of this source's results can appear in
    the final merged list — `None` means uncapped (the primary source).
    """

    name: str
    provider: SearchProvider
    weight: float
    max_results: int | None = None


class CompositeSearchProvider:
    """Fans out to multiple SearchProviders and merges their results.

    Deliberately does NOT compute a blended cross-source relevance score.
    A prior system that did (score = relevance + recency + source weight,
    naive token-overlap relevance) let noisy low-signal sources outscore
    genuinely relevant results on niche queries, because literal-token
    overlap isn't comparable across source types and nothing structurally
    bounded one source's share of the top-K.

    Instead: weighted round-robin interleaving (the same algorithm nginx
    uses for weighted upstream balancing) plus a hard per-source result
    cap. Neither depends on a cross-source score, so neither can be fooled
    by it — and the cap guarantees, by construction, that a noisy source
    can never occupy more than its allotted slots.
    """

    def __init__(self, sources: list[WeightedSource], *, per_source_timeout_seconds: float = 15.0):
        if not sources:
            raise ValueError("CompositeSearchProvider needs at least one source")
        self._sources = sources
        self._per_source_timeout_seconds = per_source_timeout_seconds

    async def _fetch(
        self, source: WeightedSource, query: str, limit: int, hints: WeatherHint | None = None
    ) -> tuple[str, list[SearchResult]]:
        fetch_limit = min(source.max_results, limit) if source.max_results is not None else limit
        if fetch_limit <= 0:
            return source.name, []
        try:
            async with asyncio.timeout(self._per_source_timeout_seconds):
                # `hints` reaches ONLY the weather source — every other
                # source's call is untouched, so the shared SearchProvider
                # Protocol and its other implementers need no changes.
                if source.name == "weather":
                    raw = await source.provider.search(query, fetch_limit, hints=hints)
                else:
                    raw = await source.provider.search(query, fetch_limit)
        except Exception:
            logger.warning(
                "search source %r failed; continuing without it", source.name, exc_info=True
            )
            return source.name, []
        return source.name, [dataclasses.replace(r, source=source.name) for r in raw]

    async def search(
        self, query: str, limit: int, hints: WeatherHint | None = None
    ) -> list[SearchResult]:
        fetched = await asyncio.gather(
            *(self._fetch(source, query, limit, hints) for source in self._sources)
        )
        by_name = dict(fetched)

        # Dedup by normalized URL, higher-weight source first, so a shared
        # URL is attributed to the more-trusted source and never consumes
        # two sources' slots.
        seen: set[str] = set()
        queues: dict[str, deque[SearchResult]] = {}
        for source in sorted(self._sources, key=lambda s: -s.weight):
            deduped = []
            for result in by_name[source.name]:
                key = normalize_url(result.url)
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(result)
            queues[source.name] = deque(deduped)

        # Smooth weighted round-robin: each active source accrues its
        # weight every tick, the highest accrual is picked and docked by
        # the total active weight. Proportionally interleaves by weight
        # without ever computing a cross-source relevance score.
        active = [s for s in self._sources if queues[s.name]]
        current = {s.name: 0.0 for s in active}
        merged: list[SearchResult] = []
        while active and len(merged) < limit:
            for source in active:
                current[source.name] += source.weight
            picked = max(active, key=lambda s: current[s.name])
            current[picked.name] -= sum(s.weight for s in active)
            merged.append(queues[picked.name].popleft())
            if not queues[picked.name]:
                active.remove(picked)
                current.pop(picked.name, None)

        return [dataclasses.replace(r, rank=i) for i, r in enumerate(merged, start=1)]
