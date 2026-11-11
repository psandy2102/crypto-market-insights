"""PostgreSQL persistence and data-health queries for candle ingestion."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
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
    create_engine,
    func,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import StaticPool

from crypto_market_insights.market_data import VenueCandle

LOGGER = logging.getLogger(__name__)
metadata = MetaData()
json_type = JSON().with_variant(JSONB(), "postgresql")

ingestion_runs = Table(
    "candle_ingestion_runs",
    metadata,
    # UUID IDs are also returned to callers for provider and ingestion correlation.
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("venue", String(40), nullable=False),
    Column("venue_pair", String(80), nullable=False),
    Column("interval", String(16), nullable=False),
    Column("status", String(16), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True)),
    Column("received_count", Integer, nullable=False, default=0),
    Column("upserted_count", Integer, nullable=False, default=0),
    Column("diagnostics", json_type, nullable=False, default=list),
    Column("error_message", String),
    CheckConstraint("status IN ('running', 'succeeded', 'failed')"),
)

candles = Table(
    "candles",
    metadata,
    Column(
        "id",
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    ),
    Column("venue", String(40), nullable=False),
    Column("venue_pair", String(80), nullable=False),
    Column("base_symbol", String(20), nullable=False),
    Column("quote_symbol", String(20), nullable=False),
    Column("interval", String(16), nullable=False),
    Column("open_time", DateTime(timezone=True), nullable=False),
    Column("close_time", DateTime(timezone=True), nullable=False),
    Column("open", Numeric(38, 18), nullable=False),
    Column("high", Numeric(38, 18), nullable=False),
    Column("low", Numeric(38, 18), nullable=False),
    Column("close", Numeric(38, 18), nullable=False),
    Column("volume", Numeric(38, 18), nullable=False),
    Column("is_complete", Boolean, nullable=False),
    Column("source_timestamp", DateTime(timezone=True), nullable=False),
    Column("retrieved_at", DateTime(timezone=True), nullable=False),
    Column(
        "ingestion_run_id",
        Uuid(as_uuid=True),
        ForeignKey("candle_ingestion_runs.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    CheckConstraint("close_time > open_time"),
    CheckConstraint(
        "open > 0 AND high > 0 AND low > 0 AND close > 0 "
        "AND high >= low AND high >= open AND high >= close "
        "AND low <= open AND low <= close"
    ),
    CheckConstraint("volume >= 0"),
    Index(
        "candles_unique_key",
        "venue",
        "venue_pair",
        "interval",
        "open_time",
        unique=True,
    ),
    Index("candles_freshness_idx", "venue", "venue_pair", "interval", "close_time"),
)

provider_health = Table(
    "candle_provider_health",
    metadata,
    Column("venue", String(40), primary_key=True),
    Column("status", String(16), nullable=False),
    Column("last_attempt_at", DateTime(timezone=True), nullable=False),
    Column("last_success_at", DateTime(timezone=True)),
    Column("last_error", String),
    Column(
        "last_run_id",
        Uuid(as_uuid=True),
        ForeignKey("candle_ingestion_runs.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    CheckConstraint("status IN ('healthy', 'degraded')"),
)


class CandleRepository:
    """Transactional candle, ingestion-run, and provider-health store."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def start_run(self, *, venue: str, venue_pair: str, interval: str) -> uuid.UUID:
        run_id = uuid.uuid4()
        now = datetime.now(UTC)
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    ingestion_runs.insert().values(
                        id=run_id,
                        venue=venue,
                        venue_pair=venue_pair,
                        interval=interval,
                        status="running",
                        started_at=now,
                        diagnostics=[],
                    )
                )
                self._upsert_provider_health(
                    connection,
                    {
                        "venue": venue,
                        "status": "degraded",
                        "last_attempt_at": now,
                        "last_success_at": None,
                        "last_error": "Ingestion is running.",
                        "last_run_id": run_id,
                    },
                    preserve_last_success=True,
                )
        except SQLAlchemyError:
            LOGGER.exception(
                "Could not create candle ingestion run",
                extra={"venue": venue, "venue_pair": venue_pair, "interval": interval},
            )
            raise
        return run_id

    def complete_run(
        self,
        *,
        run_id: uuid.UUID,
        venue: str,
        candles_to_store: list[VenueCandle],
        diagnostics: list[dict[str, Any]],
        received_count: int,
    ) -> int:
        now = datetime.now(UTC)
        records = [
            {
                "venue": candle.venue,
                "venue_pair": candle.venue_pair,
                "base_symbol": candle.base_symbol,
                "quote_symbol": candle.quote_symbol,
                "interval": candle.interval,
                "open_time": candle.open_time,
                "close_time": candle.close_time,
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "volume": candle.volume,
                "is_complete": candle.is_complete,
                "source_timestamp": candle.source_timestamp,
                "retrieved_at": candle.retrieved_at,
                "ingestion_run_id": run_id,
            }
            for candle in candles_to_store
        ]
        try:
            with self._engine.begin() as connection:
                for record in records:
                    self._upsert_candle(connection, record)
                connection.execute(
                    update(ingestion_runs)
                    .where(ingestion_runs.c.id == run_id)
                    .values(
                        status="succeeded",
                        completed_at=now,
                        received_count=received_count,
                        upserted_count=len(records),
                        diagnostics=diagnostics,
                        error_message=None,
                    )
                )
                connection.execute(
                    update(provider_health)
                    .where(provider_health.c.venue == venue)
                    .values(
                        status="healthy",
                        last_success_at=now,
                        last_error=None,
                    )
                )
        except SQLAlchemyError:
            LOGGER.exception(
                "Could not persist candle ingestion",
                extra={"venue": venue, "run_id": str(run_id)},
            )
            raise
        return len(records)

    def fail_run(
        self,
        *,
        run_id: uuid.UUID,
        venue: str,
        error: Exception,
        diagnostics: list[dict[str, Any]],
        received_count: int = 0,
    ) -> None:
        now = datetime.now(UTC)
        message = str(error)[:2000]
        try:
            with self._engine.begin() as connection:
                connection.execute(
                    update(ingestion_runs)
                    .where(ingestion_runs.c.id == run_id)
                    .values(
                        status="failed",
                        completed_at=now,
                        received_count=received_count,
                        diagnostics=diagnostics,
                        error_message=message,
                    )
                )
                health_values = {
                    "venue": venue,
                    "status": "degraded",
                    "last_attempt_at": now,
                    "last_success_at": None,
                    "last_error": message,
                    "last_run_id": run_id,
                }
                self._upsert_provider_health(
                    connection,
                    health_values,
                    preserve_last_success=True,
                )
        except SQLAlchemyError:
            LOGGER.exception(
                "Could not record failed candle ingestion",
                extra={"venue": venue, "run_id": str(run_id)},
            )
            raise

    def get_data_health(self, *, failed_limit: int = 10) -> dict[str, Any]:
        if failed_limit < 1:
            raise ValueError("failed_limit must be at least 1.")
        with self._engine.connect() as connection:
            health_rows = connection.execute(
                select(provider_health).order_by(provider_health.c.venue)
            ).mappings()
            providers = [dict(row) for row in health_rows]
            latest_rows = connection.execute(
                select(
                    candles.c.venue,
                    candles.c.venue_pair,
                    candles.c.interval,
                    func.max(candles.c.close_time).label("latest_close_time"),
                    func.max(candles.c.retrieved_at).label("last_retrieved_at"),
                    func.count(candles.c.id).label("candle_count"),
                )
                .where(candles.c.is_complete.is_(True))
                .group_by(candles.c.venue, candles.c.venue_pair, candles.c.interval)
                .order_by(candles.c.venue, candles.c.venue_pair, candles.c.interval)
            ).mappings()
            freshness = [dict(row) for row in latest_rows]
            failed_rows = connection.execute(
                select(ingestion_runs)
                .where(ingestion_runs.c.status == "failed")
                .order_by(ingestion_runs.c.completed_at.desc())
                .limit(failed_limit)
            ).mappings()
            failures = [dict(row) for row in failed_rows]
        return {
            "providers": providers,
            "freshness": freshness,
            "recent_failed_runs": failures,
        }

    @staticmethod
    def _upsert_candle(connection: Any, record: dict[str, Any]) -> None:
        dialect_name = connection.dialect.name
        statement: Any
        if dialect_name == "postgresql":
            statement = postgresql_insert(candles).values(**record)
            excluded = statement.excluded
        elif dialect_name == "sqlite":
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert

            statement = sqlite_insert(candles).values(**record)
            excluded = statement.excluded
        else:
            raise RuntimeError(f"Unsupported candle database dialect: {dialect_name}")

        statement = statement.on_conflict_do_update(
            index_elements=[
                candles.c.venue,
                candles.c.venue_pair,
                candles.c.interval,
                candles.c.open_time,
            ],
            set_={
                column.name: getattr(excluded, column.name)
                for column in candles.columns
                if column.name not in {"id", "venue", "venue_pair", "interval", "open_time"}
            },
        )
        connection.execute(statement)

    @staticmethod
    def _upsert_provider_health(
        connection: Any,
        values: dict[str, Any],
        *,
        preserve_last_success: bool = False,
    ) -> None:
        dialect_name = connection.dialect.name
        statement: Any
        if dialect_name == "postgresql":
            statement = postgresql_insert(provider_health).values(**values)
        elif dialect_name == "sqlite":
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert

            statement = sqlite_insert(provider_health).values(**values)
        else:
            raise RuntimeError(f"Unsupported provider health database dialect: {dialect_name}")
        excluded = statement.excluded
        connection.execute(
            statement.on_conflict_do_update(
                index_elements=[provider_health.c.venue],
                set_={
                    column.name: getattr(excluded, column.name)
                    for column in provider_health.columns
                    if column.name != "venue"
                    and not (preserve_last_success and column.name == "last_success_at")
                },
            )
        )


def create_database_engine(database_url: str) -> Engine:
    """Create the SQLAlchemy engine used by API dependencies and migrations."""
    normalized_url = database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if normalized_url.startswith("sqlite:///:memory:"):
        return create_engine(
            normalized_url,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    return create_engine(normalized_url, pool_pre_ping=True)
