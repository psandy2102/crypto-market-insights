"""Persist RSS feed runs, canonical news articles, sources, and health.

Revision ID: 0004_news_ingestion
Revises: 0003_risk_gates_no_trade
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_news_ingestion"
down_revision = "0003_risk_gates_no_trade"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "news_feed_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("feed_id", sa.String(80), nullable=False),
        sa.Column("url", sa.String(2000), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("articles_received", sa.Integer, nullable=False, server_default="0"),
        sa.Column("articles_persisted", sa.Integer, nullable=False, server_default="0"),
        sa.Column("canonical_articles_added", sa.Integer, nullable=False, server_default="0"),
        sa.Column("duplicates_collapsed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_message", sa.String(2000)),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="news_feed_runs_status_check",
        ),
        sa.CheckConstraint(
            "articles_received >= 0 AND articles_persisted >= 0 "
            "AND canonical_articles_added >= 0 AND duplicates_collapsed >= 0",
            name="news_feed_runs_counts_check",
        ),
    )
    op.create_index(
        "news_feed_runs_feed_started_idx",
        "news_feed_runs",
        ["feed_id", "started_at"],
    )

    op.create_table(
        "news_feed_health",
        sa.Column("feed_id", sa.String(80), primary_key=True),
        sa.Column("url", sa.String(2000), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.String(2000)),
        sa.Column(
            "last_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("news_feed_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('polling', 'healthy', 'degraded')",
            name="news_feed_health_status_check",
        ),
    )

    op.create_table(
        "news_articles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("canonical_url", sa.String(2000), nullable=False),
        sa.Column("title", sa.String(1000), nullable=False),
        sa.Column("publisher", sa.String(500), nullable=False),
        sa.Column("language", sa.String(35), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("excerpt", sa.String(1000)),
        sa.Column("title_fingerprint", sa.String(64), nullable=False),
        sa.Column("source_count", sa.Integer, nullable=False, server_default="1"),
        sa.UniqueConstraint("canonical_url", name="news_articles_canonical_url_unique"),
    )
    op.create_index("news_articles_published_idx", "news_articles", ["published_at"])
    op.create_index(
        "news_articles_fingerprint_idx",
        "news_articles",
        ["title_fingerprint", "published_at"],
    )

    op.create_table(
        "news_article_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "article_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("news_articles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("feed_id", sa.String(80), nullable=False),
        sa.Column("source_url", sa.String(2000), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("excerpt", sa.String(1000)),
    )


def downgrade() -> None:
    op.drop_table("news_article_sources")
    op.drop_index("news_articles_fingerprint_idx", table_name="news_articles")
    op.drop_index("news_articles_published_idx", table_name="news_articles")
    op.drop_table("news_articles")
    op.drop_table("news_feed_health")
    op.drop_index("news_feed_runs_feed_started_idx", table_name="news_feed_runs")
    op.drop_table("news_feed_runs")
