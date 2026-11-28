"""Persistence for validated source-grounded LLM summaries."""

import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, Column, DateTime, MetaData, String, Table, Uuid
from sqlalchemy.dialects.postgresql import JSONB

from crypto_market_insights.llm_summaries import GroundedSummary

llm_summary_metadata = MetaData()
_json_type = JSON().with_variant(JSONB(), "postgresql")

llm_summaries = Table(
    "llm_summaries",
    llm_summary_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("model_identity", String(200), nullable=False),
    Column("prompt_version", String(80), nullable=False),
    Column("generation_parameters", _json_type, nullable=False),
    Column("article_ids", _json_type, nullable=False),
    Column("deterministic_features", _json_type, nullable=False),
    Column("result", _json_type, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


class LlmSummaryRepository:
    """Store only validated generated summaries and their evidence metadata."""

    def __init__(self, engine: Any) -> None:
        self._engine = engine

    def save_summary(
        self,
        *,
        model_identity: str,
        prompt_version: str,
        generation_parameters: Mapping[str, int | float],
        article_ids: Sequence[UUID],
        deterministic_features: Mapping[str, Any],
        result: GroundedSummary,
    ) -> UUID:
        summary_id = uuid.uuid4()
        with self._engine.begin() as connection:
            connection.execute(
                llm_summaries.insert().values(
                    id=summary_id,
                    model_identity=model_identity,
                    prompt_version=prompt_version,
                    generation_parameters=dict(generation_parameters),
                    article_ids=[str(article_id) for article_id in article_ids],
                    deterministic_features=dict(deterministic_features),
                    result=result.model_dump(mode="json"),
                    created_at=datetime.now(UTC),
                )
            )
        return summary_id
