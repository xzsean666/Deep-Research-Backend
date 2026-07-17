from datetime import UTC, datetime, timedelta

from app.models import SourceType
from app.services.document.ttl import classify_source_type, compute_expires_at


def test_classifies_github():
    assert classify_source_type("https://github.com/anthropics/claude") == SourceType.GITHUB
    assert classify_source_type("https://raw.githubusercontent.com/x/y/z") == SourceType.GITHUB


def test_classifies_docs():
    assert classify_source_type("https://docs.python.org/3/") == SourceType.DOCS
    assert classify_source_type("https://myproject.readthedocs.io/en/latest/") == SourceType.DOCS


def test_classifies_news():
    assert classify_source_type("https://www.bbc.com/news/world") == SourceType.NEWS


def test_defaults_to_blog():
    assert classify_source_type("https://some-random-blog.example.com/post") == SourceType.BLOG


def test_expiry_uses_ttl_for_source_type(settings):
    fetched_at = datetime(2026, 1, 1, tzinfo=UTC)

    assert compute_expires_at(SourceType.DOCS, fetched_at, settings) == fetched_at + timedelta(
        days=settings.ttl_docs_days
    )
    assert compute_expires_at(SourceType.NEWS, fetched_at, settings) == fetched_at + timedelta(
        hours=settings.ttl_news_hours
    )
