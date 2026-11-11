"""Create candle ingestion, provider health, and OHLCV tables.

Revision ID: 0001_candle_ingestion
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_candle_ingestion"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "candle_ingestion_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("venue", sa.String(40), nullable=False),
        sa.Column("venue_pair", sa.String(80), nullable=False),
        sa.Column("interval", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("received_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("upserted_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "diagnostics",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("error_message", sa.Text),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="candle_ingestion_runs_status_check",
        ),
    )
    op.create_index(
        "candle_ingestion_runs_started_idx",
        "candle_ingestion_runs",
        ["started_at"],
    )
    op.create_index(
        "candle_ingestion_runs_failed_idx",
        "candle_ingestion_runs",
        ["completed_at"],
        postgresql_where=sa.text("status = 'failed'"),
    )

    op.create_table(
        "candles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("venue", sa.String(40), nullable=False),
        sa.Column("venue_pair", sa.String(80), nullable=False),
        sa.Column("base_symbol", sa.String(20), nullable=False),
        sa.Column("quote_symbol", sa.String(20), nullable=False),
        sa.Column("interval", sa.String(16), nullable=False),
        sa.Column("open_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("close_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(38, 18), nullable=False),
        sa.Column("high", sa.Numeric(38, 18), nullable=False),
        sa.Column("low", sa.Numeric(38, 18), nullable=False),
        sa.Column("close", sa.Numeric(38, 18), nullable=False),
        sa.Column("volume", sa.Numeric(38, 18), nullable=False),
        sa.Column("is_complete", sa.Boolean, nullable=False),
        sa.Column("source_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingestion_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint("close_time > open_time", name="candles_time_check"),
        sa.CheckConstraint(
            "open > 0 AND high > 0 AND low > 0 AND close > 0 "
            "AND high >= low AND high >= open AND high >= close "
            "AND low <= open AND low <= close",
            name="candles_ohlc_check",
        ),
        sa.CheckConstraint("volume >= 0", name="candles_volume_check"),
        sa.ForeignKeyConstraint(
            ["ingestion_run_id"],
            ["candle_ingestion_runs.id"],
            ondelete="RESTRICT",
            name="candles_ingestion_run_fk",
        ),
    )
    op.create_index(
        "candles_unique_key",
        "candles",
        ["venue", "venue_pair", "interval", "open_time"],
        unique=True,
    )
    op.create_index(
        "candles_freshness_idx",
        "candles",
        ["venue", "venue_pair", "interval", "close_time"],
    )

    op.create_table(
        "candle_provider_health",
        sa.Column("venue", sa.String(40), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text),
        sa.Column("last_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('healthy', 'degraded')",
            name="candle_provider_health_status_check",
        ),
        sa.ForeignKeyConstraint(
            ["last_run_id"],
            ["candle_ingestion_runs.id"],
            ondelete="RESTRICT",
            name="candle_provider_health_last_run_fk",
        ),
    )


def downgrade() -> None:
    op.drop_table("candle_provider_health")
    op.drop_index("candles_freshness_idx", table_name="candles")
    op.drop_index("candles_unique_key", table_name="candles")
    op.drop_table("candles")
    op.drop_index(
        "candle_ingestion_runs_failed_idx",
        table_name="candle_ingestion_runs",
    )
    op.drop_index(
        "candle_ingestion_runs_started_idx",
        table_name="candle_ingestion_runs",
    )
    op.drop_table("candle_ingestion_runs")
