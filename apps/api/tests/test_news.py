from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from crypto_market_insights.candle_storage import create_database_engine
from crypto_market_insights.dependencies import get_news_repository
from crypto_market_insights.main import app
from crypto_market_insights.news import (
    NewsArticle,
    NewsProviderError,
    RssNewsProvider,
    canonicalize_url,
    parse_feed_configuration,
    parse_feed_xml,
)
from crypto_market_insights.news_storage import (
    NewsRepository,
    news_metadata,
)

RETRIEVED_AT = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
RSS_XML = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Example Crypto News</title>
    <item>
      <title>Bitcoin ETF approval reported</title>
      <link>https://www.example.com/story?id=42&amp;utm_source=rss#section</link>
      <pubDate>Tue, 25 Nov 2026 11:30:00 GMT</pubDate>
      <description>Permitted &lt;b&gt;excerpt&lt;/b&gt; text.</description>
      <author>Example Publisher</author>
    </item>
    <item>
      <title>Bitcoin ETF approval reported</title>
      <guid>https://mirror.example/story?id=42</guid>
      <pubDate>2026-11-25T11:31:00Z</pubDate>
      <description>Same syndicated story.</description>
      <author>Mirror Publisher</author>
    </item>
  </channel>
</rss>
"""


def test_canonicalize_url_removes_tracking_fragment_and_normalizes_host() -> None:
    canonical = canonicalize_url("HTTPS://WWW.Example.COM/path?utm_source=rss&b=2&a=1#section")

    assert canonical == "https://example.com/path?a=1&b=2"


def test_parse_feed_configuration_accepts_unique_explicit_feeds() -> None:
    assert parse_feed_configuration(
        "primary=https://example.com/rss.xml; secondary=https://mirror.example/feed"
    ) == [
        ("primary", "https://example.com/rss.xml"),
        ("secondary", "https://mirror.example/feed"),
    ]
    with pytest.raises(ValueError, match="unique"):
        parse_feed_configuration("one=https://example.com/rss;one=https://example.com/other")


def test_rss_parser_normalizes_metadata_and_limits_excerpt() -> None:
    articles = parse_feed_xml(
        RSS_XML,
        feed_id="primary",
        retrieved_at=RETRIEVED_AT,
        allowed_excerpt_chars=12,
    )

    assert len(articles) == 2
    assert articles[0].title == "Bitcoin ETF approval reported"
    assert articles[0].publisher == "Example Publisher"
    assert articles[0].published_at == datetime(2026, 11, 25, 11, 30, tzinfo=UTC)
    assert articles[0].retrieved_at == RETRIEVED_AT
    assert articles[0].excerpt is not None
    assert len(articles[0].excerpt) <= 15
    assert articles[0].canonical_url.startswith("https://")


def test_repository_persists_article_and_collapses_syndicated_duplicates() -> None:
    engine = create_database_engine("sqlite:///:memory:")
    news_metadata.create_all(engine)
    repository = NewsRepository(engine)
    run_id = repository.start_feed_run(
        "primary",
        "https://example.com/rss.xml",
        RETRIEVED_AT,
    )
    article = NewsArticle(
        canonical_url="https://example.com/story/1",
        source_url="https://example.com/story/1",
        title="Bitcoin ETF approval reported",
        publisher="Example Publisher",
        language="en",
        published_at=RETRIEVED_AT - timedelta(minutes=30),
        retrieved_at=RETRIEVED_AT,
        excerpt="Permitted excerpt.",
        feed_id="primary",
    )
    syndicated = article.model_copy(
        update={
            "canonical_url": "https://mirror.example/story/1",
            "source_url": "https://mirror.example/story/1",
            "publisher": "Example Publisher",
            "feed_id": "mirror",
        }
    )

    assert repository.persist_article(article) is True
    assert repository.persist_article(syndicated) is False
    repository.complete_feed_run(
        run_id,
        articles_received=2,
        articles_persisted=2,
        canonical_articles_added=1,
        duplicates_collapsed=1,
    )

    articles = repository.get_articles()
    health = repository.get_health(stale_after_seconds=3600)
    assert len(articles) == 1
    assert articles[0]["source_count"] == 2
    assert health["feeds"][0]["status"] == "healthy"
    assert health["feeds"][0]["stale"] is False
    assert health["recent_runs"][0]["duplicates_collapsed"] == 1
    engine.dispose()


def test_provider_visible_errors_and_retry_are_bounded() -> None:
    attempts = 0

    def transport(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, request=request)

    delays: list[float] = []
    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        provider = RssNewsProvider(
            client=client,
            max_attempts=2,
            retry_base_delay=0.25,
            sleep=delays.append,
        )
        with pytest.raises(NewsProviderError, match="HTTP 503") as error:
            provider.fetch(feed_id="primary", url="https://example.com/rss")

    assert attempts == 2
    assert delays == [0.25]
    assert error.value.error_code == "feed_http_error"
    assert error.value.retryable is True


def test_news_api_polls_and_exposes_health() -> None:
    engine = create_database_engine("sqlite:///:memory:")
    news_metadata.create_all(engine)
    repository = NewsRepository(engine)
    app.dependency_overrides[get_news_repository] = lambda: repository

    try:
        articles = TestClient(app).get("/api/v1/news/articles")
        health = TestClient(app).get("/api/v1/news/health")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert articles.status_code == 200
    assert articles.json() == []
    assert health.status_code == 200
    assert health.json() == {"feeds": [], "recent_runs": []}
