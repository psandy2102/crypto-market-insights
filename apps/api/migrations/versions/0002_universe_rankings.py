"""Persist point-in-time universe decisions and component scores.

Revision ID: 0002_universe_rankings
Revises: 0001_candle_ingestion
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_universe_rankings"
down_revision = "0001_candle_ingestion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "universe_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("venue", sa.String(40), nullable=False),
        sa.Column("quote_currency", sa.String(20), nullable=False),
        sa.Column("metadata_provider", sa.String(40), nullable=False),
        sa.Column("universe_version", sa.String(64), nullable=False),
        sa.Column("ranking_strategy_version", sa.String(64), nullable=False),
        sa.Column("requested_size", sa.Integer, nullable=False),
        sa.Column("candidate_count", sa.Integer, nullable=False),
        sa.Column("selected_count", sa.Integer, nullable=False),
        sa.Column("no_trade", sa.Boolean, nullable=False),
        sa.Column("ranking_weights", postgresql.JSONB, nullable=False),
        sa.CheckConstraint("requested_size > 0", name="universe_runs_size_check"),
        sa.CheckConstraint(
            "candidate_count >= 0 AND selected_count >= 0 AND selected_count <= requested_size",
            name="universe_runs_count_check",
        ),
    )
    op.create_index("universe_runs_evaluated_idx", "universe_runs", ["evaluated_at"])

    op.create_table(
        "universe_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("universe_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provider_asset_id", sa.String(128), nullable=False),
        sa.Column("canonical_asset_id", sa.String(128), nullable=False),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("venue_pair", sa.String(80)),
        sa.Column("asset_types", postgresql.JSONB, nullable=False),
        sa.Column("history_timeframe", sa.String(16), nullable=False),
        sa.Column("market_cap", sa.Numeric(38, 18)),
        sa.Column("quote_volume", sa.Numeric(38, 18)),
        sa.Column("metadata_source_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("history_candle_count", sa.Integer, nullable=False),
        sa.Column("history_as_of", sa.DateTime(timezone=True)),
        sa.Column("data_quality_score", sa.Numeric(6, 3)),
        sa.Column("eligible", sa.Boolean, nullable=False),
        sa.Column("selected", sa.Boolean, nullable=False),
        sa.Column("selection_rank", sa.Integer),
        sa.Column("exclusion_reasons", postgresql.JSONB, nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True)),
        sa.Column("effective_to", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "run_id",
            "provider_asset_id",
            name="universe_membership_run_asset_unique",
        ),
        sa.CheckConstraint(
            "history_candle_count >= 0",
            name="universe_membership_history_count_check",
        ),
        sa.CheckConstraint(
            "data_quality_score IS NULL OR data_quality_score BETWEEN 0 AND 100",
            name="universe_membership_quality_check",
        ),
        sa.CheckConstraint(
            "(selected = FALSE AND effective_from IS NULL AND selection_rank IS NULL) "
            "OR (selected = TRUE AND eligible = TRUE AND effective_from IS NOT NULL "
            "AND selection_rank > 0)",
            name="universe_membership_effective_check",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="universe_membership_period_check",
        ),
    )
    op.create_index(
        "universe_membership_asset_effective_idx",
        "universe_memberships",
        ["provider_asset_id", "effective_from", "effective_to"],
    )
    op.create_index(
        "universe_membership_current_idx",
        "universe_memberships",
        ["effective_to", "selected"],
    )

    op.create_table(
        "universe_rankings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("universe_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provider_asset_id", sa.String(128), nullable=False),
        sa.Column("canonical_asset_id", sa.String(128), nullable=False),
        sa.Column("symbol", sa.String(40), nullable=False),
        sa.Column("venue_pair", sa.String(80), nullable=False),
        sa.Column("strategy_version", sa.String(64), nullable=False),
        sa.Column("component_scores", postgresql.JSONB),
        sa.Column("total_score", sa.Numeric(6, 2)),
        sa.Column("rank", sa.Integer),
        sa.Column("gate_failures", postgresql.JSONB, nullable=False),
        sa.UniqueConstraint(
            "run_id",
            "provider_asset_id",
            name="universe_ranking_run_asset_unique",
        ),
        sa.CheckConstraint(
            "total_score IS NULL OR total_score BETWEEN 0 AND 100",
            name="universe_ranking_total_score_check",
        ),
        sa.CheckConstraint("rank IS NULL OR rank > 0", name="universe_ranking_rank_check"),
        sa.CheckConstraint(
            "(component_scores IS NULL AND total_score IS NULL AND rank IS NULL) "
            "OR (component_scores IS NOT NULL AND total_score IS NOT NULL)",
            name="universe_ranking_score_fields_check",
        ),
    )
    op.create_index("universe_rankings_run_rank_idx", "universe_rankings", ["run_id", "rank"])


def downgrade() -> None:
    op.drop_index("universe_rankings_run_rank_idx", table_name="universe_rankings")
    op.drop_table("universe_rankings")
    op.drop_index(
        "universe_membership_current_idx",
        table_name="universe_memberships",
    )
    op.drop_index(
        "universe_membership_asset_effective_idx",
        table_name="universe_memberships",
    )
    op.drop_table("universe_memberships")
    op.drop_index("universe_runs_evaluated_idx", table_name="universe_runs")
    op.drop_table("universe_runs")
