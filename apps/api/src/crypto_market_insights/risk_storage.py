"""Persistence for risk-gate decisions and No Trade outcomes."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    MetaData,
    Numeric,
    String,
    Table,
    Uuid,
    func,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine

from crypto_market_insights.risk_gates import RiskGateResult

risk_metadata = MetaData()
json_type = JSON().with_variant(JSONB(), "postgresql")

risk_decisions = Table(
    "risk_decisions",
    risk_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("candidate_asset_id", String(128), nullable=False),
    Column("strategy_version", String(64), nullable=False),
    Column("outcome", String(16), nullable=False),
    Column("approved", Boolean, nullable=False),
    Column("evaluated_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("post_cost_reward_risk", Numeric(12, 6)),
    Column("reasons", json_type, nullable=False),
    Index("risk_decisions_asset_evaluated_idx", "candidate_asset_id", "evaluated_at"),
)

risk_decision_events = Table(
    "risk_decision_events",
    risk_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column(
        "decision_id",
        Uuid(as_uuid=True),
        ForeignKey("risk_decisions.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("code", String(80), nullable=False),
    Column("message", String(2000), nullable=False),
    Column("evaluated_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Index("risk_decision_events_code_idx", "code", "evaluated_at"),
)


class RiskDecisionRepository:
    """Persist immutable risk-gate decisions and machine-readable reasons."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def persist(self, result: RiskGateResult) -> uuid.UUID:
        decision_id = uuid.uuid4()
        with self._engine.begin() as connection:
            previous: datetime | None = connection.execute(
                select(func.max(risk_decisions.c.evaluated_at)).where(
                    risk_decisions.c.candidate_asset_id == result.candidate_asset_id
                )
            ).scalar_one()
            if previous is not None:
                if previous.tzinfo is None:
                    previous = previous.replace(tzinfo=UTC)
                if result.evaluated_at <= previous:
                    raise ValueError("Risk decisions must be persisted in increasing time order.")

            connection.execute(
                update(risk_decisions)
                .where(
                    risk_decisions.c.candidate_asset_id == result.candidate_asset_id,
                    risk_decisions.c.outcome == "TRADE",
                    risk_decisions.c.expires_at > result.evaluated_at,
                )
                .values(expires_at=result.evaluated_at)
            )
            connection.execute(
                risk_decisions.insert().values(
                    id=decision_id,
                    candidate_asset_id=result.candidate_asset_id,
                    strategy_version=result.strategy_version,
                    outcome=result.outcome,
                    approved=result.approved,
                    evaluated_at=result.evaluated_at,
                    expires_at=result.expires_at,
                    post_cost_reward_risk=result.post_cost_reward_risk,
                    reasons=[
                        {"code": reason.code, "message": reason.message}
                        for reason in result.reasons
                    ],
                )
            )
            if result.reasons:
                connection.execute(
                    risk_decision_events.insert(),
                    [
                        {
                            "id": uuid.uuid4(),
                            "decision_id": decision_id,
                            "code": reason.code,
                            "message": reason.message,
                            "evaluated_at": result.evaluated_at,
                            "expires_at": result.expires_at,
                        }
                        for reason in result.reasons
                    ],
                )
        return decision_id

    def get_latest(self, *, candidate_asset_id: str | None = None) -> dict[str, Any] | None:
        with self._engine.connect() as connection:
            query = select(risk_decisions).order_by(risk_decisions.c.evaluated_at.desc())
            if candidate_asset_id is not None:
                query = query.where(
                    risk_decisions.c.candidate_asset_id == candidate_asset_id.strip()
                )
            row = connection.execute(query.limit(1)).mappings().first()
            if row is None:
                return None
            return _normalize_row(dict(row))

    def get_history(
        self,
        *,
        candidate_asset_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if limit < 1:
            raise ValueError("limit must be at least 1.")
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(risk_decisions)
                .where(risk_decisions.c.candidate_asset_id == candidate_asset_id.strip())
                .order_by(risk_decisions.c.evaluated_at.desc())
                .limit(limit)
            ).mappings()
            return [_normalize_row(dict(row)) for row in rows]


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
