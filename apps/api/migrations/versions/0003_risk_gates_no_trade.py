"""Persist risk-gate decisions and machine-readable No Trade reasons.

Revision ID: 0003_risk_gates_no_trade
Revises: 0002_universe_rankings
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_risk_gates_no_trade"
down_revision = "0002_universe_rankings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "risk_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("candidate_asset_id", sa.String(128), nullable=False),
        sa.Column("strategy_version", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("approved", sa.Boolean, nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("post_cost_reward_risk", sa.Numeric(12, 6)),
        sa.Column("reasons", postgresql.JSONB, nullable=False),
        sa.CheckConstraint(
            "outcome IN ('TRADE', 'NO_TRADE')",
            name="risk_decisions_outcome_check",
        ),
        sa.CheckConstraint(
            "(outcome = 'TRADE' AND approved = TRUE)"
            " OR (outcome = 'NO_TRADE' AND approved = FALSE)",
            name="risk_decisions_consistency_check",
        ),
        sa.CheckConstraint(
            "expires_at > evaluated_at",
            name="risk_decisions_expiry_check",
        ),
    )
    op.create_index(
        "risk_decisions_asset_evaluated_idx",
        "risk_decisions",
        ["candidate_asset_id", "evaluated_at"],
    )

    op.create_table(
        "risk_decision_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "decision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("risk_decisions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("message", sa.String(2000), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(code) > 0", name="risk_decision_events_code_check"),
        sa.CheckConstraint("length(message) > 0", name="risk_decision_events_message_check"),
    )
    op.create_index(
        "risk_decision_events_code_idx",
        "risk_decision_events",
        ["code", "evaluated_at"],
    )


def downgrade() -> None:
    op.drop_index("risk_decision_events_code_idx", table_name="risk_decision_events")
    op.drop_table("risk_decision_events")
    op.drop_index(
        "risk_decisions_asset_evaluated_idx",
        table_name="risk_decisions",
    )
    op.drop_table("risk_decisions")
