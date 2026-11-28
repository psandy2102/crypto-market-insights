"""SQLAlchemy persistence for RSS provenance, canonical articles, and feed health."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Uuid,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB

from crypto_market_insights.news import NewsArticle, title_fingerprint

news_metadata = MetaData()
json_type = JSON().with_variant(JSONB(), "postgresql")

news_feed_runs = Table(
    "news_feed_runs",
    news_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("feed_id", String(80), nullable=False),
    Column("url", String(2000), nullable=False),
    Column("status", String(16), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True)),
    Column("articles_received", Integer, nullable=False, default=0),
    Column("articles_persisted", Integer, nullable=False, default=0),
    Column("canonical_articles_added", Integer, nullable=False, default=0),
    Column("duplicates_collapsed", Integer, nullable=False, default=0),
    Column("error_code", String(80)),
    Column("error_message", String(2000)),
    Index("news_feed_runs_feed_started_idx", "feed_id", "started_at"),
)

news_feed_health = Table(
    "news_feed_health",
    news_metadata,
    Column("feed_id", String(80), primary_key=True),
    Column("url", String(2000), nullable=False),
    Column("status", String(16), nullable=False),
    Column("last_attempt_at", DateTime(timezone=True), nullable=False),
    Column("last_success_at", DateTime(timezone=True)),
    Column("last_error", String(2000)),
    Column("last_run_id", Uuid(as_uuid=True), nullable=False),
)

news_articles = Table(
    "news_articles",
    news_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("canonical_url", String(2000), nullable=False),
    Column("title", String(1000), nullable=False),
    Column("publisher", String(500), nullable=False),
    Column("language", String(35), nullable=False),
    Column("published_at", DateTime(timezone=True)),
    Column("retrieved_at", DateTime(timezone=True), nullable=False),
    Column("excerpt", String(1000)),
    Column("title_fingerprint", String(64), nullable=False),
    Column("source_count", Integer, nullable=False, default=1),
    Index("news_articles_published_idx", "published_at"),
    Index("news_articles_fingerprint_idx", "title_fingerprint", "published_at"),
)

news_article_sources = Table(
    "news_article_sources",
    news_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column(
        "article_id",
        Uuid(as_uuid=True),
        ForeignKey("news_articles.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("feed_id", String(80), nullable=False),
    Column("source_url", String(2000), nullable=False),
    Column("retrieved_at", DateTime(timezone=True), nullable=False),
    Column("excerpt", String(1000)),
)


class NewsRepository:
    """Persist feed health, canonical articles, and syndication provenance."""

    def __init__(self, engine: Any) -> None:
        self._engine = engine

    def start_feed_run(self, feed_id: str, url: str, started_at: datetime) -> str:
        run_id = uuid.uuid4()
        with self._engine.begin() as connection:
            connection.execute(
                news_feed_runs.insert().values(
                    id=run_id,
                    feed_id=feed_id,
                    url=url,
                    status="running",
                    started_at=started_at,
                    articles_received=0,
                    articles_persisted=0,
                    canonical_articles_added=0,
                    duplicates_collapsed=0,
                )
            )
            existing = connection.execute(
                select(news_feed_health.c.feed_id).where(news_feed_health.c.feed_id == feed_id)
            ).first()
            if existing is None:
                connection.execute(
                    news_feed_health.insert().values(
                        feed_id=feed_id,
                        url=url,
                        status="polling",
                        last_attempt_at=started_at,
                        last_success_at=None,
                        last_error="Feed poll is in progress.",
                        last_run_id=run_id,
                    )
                )
            else:
                connection.execute(
                    update(news_feed_health)
                    .where(news_feed_health.c.feed_id == feed_id)
                    .values(
                        url=url,
                        status="polling",
                        last_attempt_at=started_at,
                        last_error="Feed poll is in progress.",
                        last_run_id=run_id,
                    )
                )
        return str(run_id)

    def persist_article(self, article: NewsArticle) -> bool:
        """Return True if a new canonical article was created."""
        fingerprint = title_fingerprint(article.title, article.publisher)
        with self._engine.begin() as connection:
            existing = (
                connection.execute(
                    select(news_articles)
                    .where(
                        (news_articles.c.canonical_url == article.canonical_url)
                        | (news_articles.c.title_fingerprint == fingerprint)
                    )
                    .order_by(news_articles.c.retrieved_at.desc())
                    .limit(1)
                )
                .mappings()
                .first()
            )

            if existing is not None:
                article_id = existing["id"]
                connection.execute(
                    update(news_articles)
                    .where(news_articles.c.id == article_id)
                    .values(source_count=news_articles.c.source_count + 1)
                )
                connection.execute(
                    news_article_sources.insert().values(
                        id=uuid.uuid4(),
                        article_id=article_id,
                        feed_id=article.feed_id,
                        source_url=article.source_url,
                        retrieved_at=article.retrieved_at,
                        excerpt=article.excerpt,
                    )
                )
                return False

            article_id = uuid.uuid4()
            connection.execute(
                news_articles.insert().values(
                    id=article_id,
                    canonical_url=article.canonical_url,
                    title=article.title,
                    publisher=article.publisher,
                    language=article.language,
                    published_at=article.published_at,
                    retrieved_at=article.retrieved_at,
                    excerpt=article.excerpt,
                    title_fingerprint=fingerprint,
                    source_count=1,
                )
            )
            connection.execute(
                news_article_sources.insert().values(
                    id=uuid.uuid4(),
                    article_id=article_id,
                    feed_id=article.feed_id,
                    source_url=article.source_url,
                    retrieved_at=article.retrieved_at,
                    excerpt=article.excerpt,
                )
            )
            return True

    def complete_feed_run(
        self,
        run_id: str,
        *,
        articles_received: int,
        articles_persisted: int,
        canonical_articles_added: int,
        duplicates_collapsed: int,
    ) -> None:
        now = datetime.now(UTC)
        run_uuid = uuid.UUID(run_id)
        with self._engine.begin() as connection:
            run = (
                connection.execute(select(news_feed_runs).where(news_feed_runs.c.id == run_uuid))
                .mappings()
                .one()
            )
            connection.execute(
                update(news_feed_runs)
                .where(news_feed_runs.c.id == run_uuid)
                .values(
                    status="succeeded",
                    completed_at=now,
                    articles_received=articles_received,
                    articles_persisted=articles_persisted,
                    canonical_articles_added=canonical_articles_added,
                    duplicates_collapsed=duplicates_collapsed,
                    error_code=None,
                    error_message=None,
                )
            )
            connection.execute(
                update(news_feed_health)
                .where(news_feed_health.c.feed_id == run["feed_id"])
                .values(
                    status="healthy",
                    last_attempt_at=now,
                    last_success_at=now,
                    last_error=None,
                    last_run_id=run_uuid,
                )
            )

    def fail_feed_run(
        self,
        run_id: str,
        *,
        error_code: str,
        error_message: str,
    ) -> None:
        now = datetime.now(UTC)
        run_uuid = uuid.UUID(run_id)
        with self._engine.begin() as connection:
            run = (
                connection.execute(select(news_feed_runs).where(news_feed_runs.c.id == run_uuid))
                .mappings()
                .one()
            )
            connection.execute(
                update(news_feed_runs)
                .where(news_feed_runs.c.id == run_uuid)
                .values(
                    status="failed",
                    completed_at=now,
                    error_code=error_code,
                    error_message=error_message[:2000],
                )
            )
            connection.execute(
                update(news_feed_health)
                .where(news_feed_health.c.feed_id == run["feed_id"])
                .values(
                    status="degraded",
                    last_attempt_at=now,
                    last_error=error_message[:2000],
                    last_run_id=run_uuid,
                )
            )

    def get_articles(self, limit: int = 50) -> list[dict[str, Any]]:
        if limit < 1:
            raise ValueError("limit must be at least 1.")
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(news_articles)
                .order_by(
                    news_articles.c.published_at.desc().nulls_last(),
                    news_articles.c.retrieved_at.desc(),
                )
                .limit(limit)
            ).mappings()
            return [_normalize_row(dict(row)) for row in rows]

    def get_articles_by_ids(self, article_ids: Sequence[UUID]) -> list[dict[str, Any]]:
        if not article_ids:
            return []
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(news_articles).where(news_articles.c.id.in_(article_ids))
            ).mappings()
            articles = {row["id"]: _normalize_row(dict(row)) for row in rows}
        return [articles[article_id] for article_id in article_ids if article_id in articles]

    def get_health(self, stale_after_seconds: int = 86400) -> dict[str, Any]:
        now = datetime.now(UTC)
        with self._engine.connect() as connection:
            feeds = connection.execute(
                select(news_feed_health).order_by(news_feed_health.c.feed_id)
            ).mappings()
            health = []
            for row in feeds:
                normalized = _normalize_row(dict(row))
                last_attempt = normalized["last_attempt_at"]
                if last_attempt.tzinfo is None:
                    last_attempt = last_attempt.replace(tzinfo=UTC)
                health.append(
                    {
                        **normalized,
                        "stale": now - last_attempt > timedelta(seconds=stale_after_seconds),
                        "stale_after_seconds": stale_after_seconds,
                    }
                )
            runs = connection.execute(
                select(news_feed_runs).order_by(news_feed_runs.c.started_at.desc()).limit(20)
            ).mappings()
            return {
                "feeds": health,
                "recent_runs": [_normalize_row(dict(row)) for row in runs],
            }


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: (
            value.replace(tzinfo=UTC)
            if isinstance(value, datetime) and value.tzinfo is None
            else value.astimezone(UTC)
            if isinstance(value, datetime)
            else value
        )
        for key, value in row.items()
    }
