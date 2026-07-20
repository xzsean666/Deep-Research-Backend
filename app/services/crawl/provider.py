from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class CrawlResult:
    """Stable shape every CrawlProvider adapter must produce.

    Nothing outside services/crawl/ should know an adapter's raw request/
    response shape — see ARCHITECTURE.md §10.
    """

    url: str
    title: str | None
    markdown: str
    metadata: dict
    published_at: datetime | None = None


class CrawlProvider(Protocol):
    async def crawl(self, url: str) -> CrawlResult: ...
