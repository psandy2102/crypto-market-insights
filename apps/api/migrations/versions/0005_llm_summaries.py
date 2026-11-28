"""Persist validated source-grounded LLM summaries.

Revision ID: 0005_llm_summaries
Revises: 0004_news_ingestion
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_llm_summaries"
down_revision = "0004_news_ingestion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_summaries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("model_identity", sa.String(200), nullable=False),
        sa.Column("prompt_version", sa.String(80), nullable=False),
        sa.Column("generation_parameters", postgresql.JSONB, nullable=False),
        sa.Column("article_ids", postgresql.JSONB, nullable=False),
        sa.Column("deterministic_features", postgresql.JSONB, nullable=False),
        sa.Column("result", postgresql.JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("llm_summaries")
