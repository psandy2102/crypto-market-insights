"""Persistence for point-in-time universe decisions and component-level rankings."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
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

from crypto_market_insights.universe import RankingResult, UniverseSelection

universe_metadata = MetaData()
json_type = JSON().with_variant(JSONB(), "postgresql")

universe_runs = Table(
    "universe_runs",
    universe_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("evaluated_at", DateTime(timezone=True), nullable=False),
    Column("venue", String(40), nullable=False),
    Column("quote_currency", String(20), nullable=False),
    Column("metadata_provider", String(40), nullable=False),
    Column("universe_version", String(64), nullable=False),
    Column("ranking_strategy_version", String(64), nullable=False),
    Column("requested_size", Integer, nullable=False),
    Column("candidate_count", Integer, nullable=False),
    Column("selected_count", Integer, nullable=False),
    Column("no_trade", Boolean, nullable=False),
    Column("ranking_weights", json_type, nullable=False),
    Index("universe_runs_evaluated_idx", "evaluated_at"),
)

universe_memberships = Table(
    "universe_memberships",
    universe_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column(
        "run_id",
        Uuid(as_uuid=True),
        ForeignKey("universe_runs.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("provider_asset_id", String(128), nullable=False),
    Column("canonical_asset_id", String(128), nullable=False),
    Column("symbol", String(40), nullable=False),
    Column("name", String(200), nullable=False),
    Column("venue_pair", String(80)),
    Column("asset_types", json_type, nullable=False),
    Column("history_timeframe", String(16), nullable=False),
    Column("market_cap", Numeric(38, 18)),
    Column("quote_volume", Numeric(38, 18)),
    Column("metadata_source_timestamp", DateTime(timezone=True), nullable=False),
    Column("metadata_retrieved_at", DateTime(timezone=True), nullable=False),
    Column("history_candle_count", Integer, nullable=False),
    Column("history_as_of", DateTime(timezone=True)),
    Column("data_quality_score", Numeric(6, 3)),
    Column("eligible", Boolean, nullable=False),
    Column("selected", Boolean, nullable=False),
    Column("selection_rank", Integer),
    Column("exclusion_reasons", json_type, nullable=False),
    Column("effective_from", DateTime(timezone=True)),
    Column("effective_to", DateTime(timezone=True)),
    Index(
        "universe_membership_asset_effective_idx",
        "provider_asset_id",
        "effective_from",
        "effective_to",
    ),
    Index("universe_membership_current_idx", "effective_to", "selected"),
)

universe_rankings = Table(
    "universe_rankings",
    universe_metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column(
        "run_id",
        Uuid(as_uuid=True),
        ForeignKey("universe_runs.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("provider_asset_id", String(128), nullable=False),
    Column("canonical_asset_id", String(128), nullable=False),
    Column("symbol", String(40), nullable=False),
    Column("venue_pair", String(80), nullable=False),
    Column("strategy_version", String(64), nullable=False),
    Column("component_scores", json_type),
    Column("total_score", Numeric(6, 2)),
    Column("rank", Integer),
    Column("gate_failures", json_type, nullable=False),
    Index("universe_rankings_run_rank_idx", "run_id", "rank"),
)


class UniverseRepository:
    """Persist auditable universe snapshots and their component-level rankings."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def persist(
        self,
        selection: UniverseSelection,
        ranking: RankingResult,
    ) -> uuid.UUID:
        """Atomically persist candidate decisions, effective memberships, and scores."""
        selected_ids = set(selection.selected_asset_ids)
        ranked_ids = {entry.provider_asset_id for entry in ranking.entries}
        if ranking.evaluated_at != selection.evaluated_at:
            raise ValueError("Universe selection and ranking timestamps must match.")
        if selected_ids != ranked_ids:
            raise ValueError("Ranking entries must exactly cover selected universe members.")

        run_id = uuid.uuid4()
        with self._engine.begin() as connection:
            latest_effective: datetime | None = connection.execute(
                select(func.max(universe_runs.c.evaluated_at)).where(
                    universe_runs.c.venue == selection.venue,
                    universe_runs.c.quote_currency == selection.quote_currency,
                )
            ).scalar_one()
            if latest_effective is not None and latest_effective.tzinfo is None:
                latest_effective = latest_effective.replace(tzinfo=UTC)
            if latest_effective is not None and selection.evaluated_at <= latest_effective:
                raise ValueError("Universe snapshots must be persisted in increasing time order.")

            connection.execute(
                update(universe_memberships)
                .where(
                    universe_memberships.c.selected.is_(True),
                    universe_memberships.c.effective_to.is_(None),
                    universe_memberships.c.effective_from.is_not(None),
                    universe_memberships.c.run_id.in_(
                        select(universe_runs.c.id).where(
                            universe_runs.c.venue == selection.venue,
                            universe_runs.c.quote_currency == selection.quote_currency,
                        )
                    ),
                )
                .values(effective_to=selection.evaluated_at)
            )
            connection.execute(
                universe_runs.insert().values(
                    id=run_id,
                    evaluated_at=selection.evaluated_at,
                    venue=selection.venue,
                    quote_currency=selection.quote_currency,
                    metadata_provider=selection.metadata_provider,
                    universe_version=selection.universe_version,
                    ranking_strategy_version=ranking.strategy_version,
                    requested_size=selection.requested_size,
                    candidate_count=len(selection.candidates),
                    selected_count=len(selection.selected_asset_ids),
                    no_trade=ranking.no_trade,
                    ranking_weights=_json_decimal(ranking.weights),
                )
            )
            if selection.candidates:
                connection.execute(
                    universe_memberships.insert(),
                    [
                        {
                            "id": uuid.uuid4(),
                            "run_id": run_id,
                            "provider_asset_id": candidate.provider_asset_id,
                            "canonical_asset_id": candidate.canonical_asset_id,
                            "symbol": candidate.symbol,
                            "name": candidate.name,
                            "venue_pair": candidate.venue_pair,
                            "asset_types": sorted(candidate.asset_types),
                            "history_timeframe": candidate.history_timeframe,
                            "market_cap": candidate.market_cap,
                            "quote_volume": candidate.quote_volume,
                            "metadata_source_timestamp": candidate.metadata_source_timestamp,
                            "metadata_retrieved_at": candidate.metadata_retrieved_at,
                            "history_candle_count": candidate.history_candle_count,
                            "history_as_of": candidate.history_as_of,
                            "data_quality_score": candidate.data_quality_score,
                            "eligible": candidate.eligible,
                            "selected": candidate.selected,
                            "selection_rank": candidate.selection_rank,
                            "exclusion_reasons": list(candidate.exclusion_reasons),
                            "effective_from": candidate.effective_from,
                            "effective_to": None,
                        }
                        for candidate in selection.candidates
                    ],
                )
            if ranking.entries:
                connection.execute(
                    universe_rankings.insert(),
                    [
                        {
                            "id": uuid.uuid4(),
                            "run_id": run_id,
                            "provider_asset_id": entry.provider_asset_id,
                            "canonical_asset_id": entry.canonical_asset_id,
                            "symbol": entry.symbol,
                            "venue_pair": entry.venue_pair,
                            "strategy_version": entry.strategy_version,
                            "component_scores": (
                                _json_decimal(entry.component_scores.model_dump())
                                if entry.component_scores is not None
                                else None
                            ),
                            "total_score": entry.total_score,
                            "rank": entry.rank,
                            "gate_failures": list(entry.gate_failures),
                        }
                        for entry in ranking.entries
                    ],
                )
        return run_id

    def get_latest(self, *, venue: str | None = None) -> dict[str, Any] | None:
        """Return the latest persisted snapshot, all eligibility decisions, and ranks."""
        with self._engine.connect() as connection:
            run_query = select(universe_runs).order_by(universe_runs.c.evaluated_at.desc())
            if venue is not None:
                run_query = run_query.where(universe_runs.c.venue == venue.strip().lower())
            run = connection.execute(run_query.limit(1)).mappings().first()
            if run is None:
                return None
            run_id = run["id"]
            run_data = _normalize_row(dict(run))
            run_data["ranking_weights"] = {
                key: Decimal(value) for key, value in run_data["ranking_weights"].items()
            }
            candidates = connection.execute(
                select(universe_memberships)
                .where(universe_memberships.c.run_id == run_id)
                .order_by(
                    universe_memberships.c.selection_rank.is_(None),
                    universe_memberships.c.selection_rank,
                    universe_memberships.c.provider_asset_id,
                )
            ).mappings()
            rankings = connection.execute(
                select(universe_rankings)
                .where(universe_rankings.c.run_id == run_id)
                .order_by(universe_rankings.c.rank.is_(None), universe_rankings.c.rank)
            ).mappings()
            ranking_rows = [_normalize_row(dict(row)) for row in rankings]
            for row in ranking_rows:
                if row["component_scores"] is not None:
                    row["component_scores"] = {
                        key: Decimal(value) for key, value in row["component_scores"].items()
                    }
            return {
                "run": run_data,
                "candidates": [_normalize_row(dict(row)) for row in candidates],
                "rankings": ranking_rows,
            }


def _json_decimal(values: dict[str, Any]) -> dict[str, Any]:
    return {
        key: str(value) if isinstance(value, Decimal) else value for key, value in values.items()
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
