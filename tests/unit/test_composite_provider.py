import asyncio

import pytest

from app.services.search.composite_provider import CompositeSearchProvider, WeightedSource
from app.services.search.provider import SearchResult


class FakeProvider:
    def __init__(self, results=None, *, raises=False, sleep_seconds=None):
        self._results = results or []
        self._raises = raises
        self._sleep_seconds = sleep_seconds

    async def search(self, query, limit):
        if self._sleep_seconds is not None:
            await asyncio.sleep(self._sleep_seconds)
        if self._raises:
            raise RuntimeError("boom")
        return self._results[:limit]


def _results(prefix: str, count: int) -> list[SearchResult]:
    return [
        SearchResult(url=f"https://{prefix}.example.com/{i}", title=f"{prefix} {i}", snippet="s", rank=i)
        for i in range(1, count + 1)
    ]


async def test_dedups_by_normalized_url_keeping_higher_weight_source():
    shared_url = "https://shared.example.com/a"
    primary = WeightedSource(
        name="primary",
        provider=FakeProvider([SearchResult(url=shared_url, title="primary copy", snippet="s", rank=1)]),
        weight=1.0,
    )
    secondary = WeightedSource(
        name="secondary",
        provider=FakeProvider([SearchResult(url=shared_url, title="secondary copy", snippet="s", rank=1)]),
        weight=0.4,
    )
    composite = CompositeSearchProvider([primary, secondary])

    results = await composite.search("q", limit=10)

    assert len(results) == 1
    assert results[0].source == "primary"
    assert results[0].title == "primary copy"


async def test_hard_cap_on_secondary_source_is_enforced_even_with_many_candidates():
    primary = WeightedSource(name="primary", provider=FakeProvider(_results("primary", 20)), weight=1.0)
    secondary = WeightedSource(
        name="secondary", provider=FakeProvider(_results("secondary", 20)), weight=0.4, max_results=2
    )
    composite = CompositeSearchProvider([primary, secondary])

    results = await composite.search("q", limit=10)

    secondary_count = sum(1 for r in results if r.source == "secondary")
    assert secondary_count <= 2


async def test_primary_dominates_final_list_proportion():
    primary = WeightedSource(name="primary", provider=FakeProvider(_results("primary", 20)), weight=1.0)
    secondary = WeightedSource(name="secondary", provider=FakeProvider(_results("secondary", 20)), weight=0.4)
    composite = CompositeSearchProvider([primary, secondary])

    results = await composite.search("q", limit=10)

    primary_count = sum(1 for r in results if r.source == "primary")
    secondary_count = sum(1 for r in results if r.source == "secondary")
    assert primary_count > secondary_count


async def test_one_source_failing_does_not_sink_the_request():
    primary = WeightedSource(name="primary", provider=FakeProvider(_results("primary", 3)), weight=1.0)
    broken = WeightedSource(name="broken", provider=FakeProvider(raises=True), weight=0.4)
    composite = CompositeSearchProvider([primary, broken])

    results = await composite.search("q", limit=10)

    assert len(results) == 3
    assert all(r.source == "primary" for r in results)


async def test_one_source_timing_out_does_not_sink_the_request():
    primary = WeightedSource(name="primary", provider=FakeProvider(_results("primary", 3)), weight=1.0)
    slow = WeightedSource(name="slow", provider=FakeProvider(sleep_seconds=1), weight=0.4)
    composite = CompositeSearchProvider([primary, slow], per_source_timeout_seconds=0.05)

    results = await composite.search("q", limit=10)

    assert len(results) == 3
    assert all(r.source == "primary" for r in results)


async def test_rank_is_renumbered_sequentially_in_final_merged_order():
    primary = WeightedSource(name="primary", provider=FakeProvider(_results("primary", 5)), weight=1.0)
    composite = CompositeSearchProvider([primary])

    results = await composite.search("q", limit=5)

    assert [r.rank for r in results] == [1, 2, 3, 4, 5]


async def test_result_truncated_to_limit():
    primary = WeightedSource(name="primary", provider=FakeProvider(_results("primary", 20)), weight=1.0)
    secondary = WeightedSource(name="secondary", provider=FakeProvider(_results("secondary", 20)), weight=0.4)
    composite = CompositeSearchProvider([primary, secondary])

    results = await composite.search("q", limit=7)

    assert len(results) == 7


def test_requires_at_least_one_source():
    with pytest.raises(ValueError):
        CompositeSearchProvider([])
