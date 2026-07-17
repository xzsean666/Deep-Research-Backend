class CrawlBlockedError(Exception):
    """Raised when a URL fails the SSRF guard (ARCHITECTURE.md §7).

    Maps to the CRAWL_BLOCKED error code in SPEC.md §2.
    """

    def __init__(self, url: str, reason: str):
        self.url = url
        self.reason = reason
        super().__init__(f"{url}: {reason}")


class CrawlFetchError(Exception):
    """Raised when the crawl provider reaches the target but fails to
    extract it (timeout, non-2xx, extraction error). Retryable by the
    worker (ARCHITECTURE.md §9) — unlike CrawlBlockedError, which never is.
    """

    def __init__(self, url: str, reason: str):
        self.url = url
        self.reason = reason
        super().__init__(f"{url}: {reason}")
