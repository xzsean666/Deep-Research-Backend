from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SearchResult:
    """Stable shape every SearchProvider adapter must produce.

    Nothing outside services/search/ should know an adapter's raw response
    shape — see ARCHITECTURE.md §10.
    """

    url: str
    title: str | None
    snippet: str | None
    rank: int
    source: str = "unknown"


class SearchProvider(Protocol):
    async def search(self, query: str, limit: int) -> list[SearchResult]: ...
