from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from crypto_market_insights import main
from crypto_market_insights.candle_ingestion import (
    CandleBatchValidator,
    CandleIngestionError,
    CandleIngestionService,
)
from crypto_market_insights.candle_storage import (
    CandleRepository,
    candles,
    create_database_engine,
    ingestion_runs,
    metadata,
    provider_health,
)
from crypto_market_insights.dependencies import get_candle_repository
from crypto_market_insights.main import app
from crypto_market_insights.market_data import VenueCandle

START = datetime(2026, 11, 11, 10, 0, tzinfo=UTC)


def make_candle(
    *,
    start: datetime = START,
    close: str = "100",
    high: str = "101",
    low: str = "99",
    is_complete: bool = True,
    retrieved_at: datetime | None = None,
) -> VenueCandle:
    return VenueCandle(
        venue="kraken",
        venue_pair="XBT/USD",
        base_symbol="BTC",
        quote_symbol="USD",
        interval="1h",
        open_time=start,
        close_time=start + timedelta(hours=1),
        open=Decimal(close),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("3.25"),
        is_complete=is_complete,
        source_timestamp=start + timedelta(hours=1),
        retrieved_at=retrieved_at or start + timedelta(minutes=5),
    )


def make_repository() -> tuple[CandleRepository, Any]:
    engine = create_database_engine("sqlite:///:memory:")
    metadata.create_all(engine)
    return CandleRepository(engine), engine


class FixtureProvider:
    venue_name = "kraken"

    def __init__(
        self,
        candles_to_return: list[VenueCandle] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._candles = candles_to_return or []
        self._error = error

    def fetch_candles(
        self,
        *,
        base_symbol: str,
        quote_symbol: str,
        interval: str,
        since: datetime | None = None,
    ) -> list[VenueCandle]:
        if self._error:
            raise self._error
        return self._candles

    def fetch_market_snapshot(self, *, base_symbol: str, quote_symbol: str) -> Any:
        raise NotImplementedError

    def close(self) -> None:
        return None


def test_validator_collapses_exact_duplicates_and_reports_gaps() -> None:
    first = make_candle()
    third = make_candle(start=START + timedelta(hours=2))
    validated, diagnostics = CandleBatchValidator().validate(
        [third, first, first],
        venue="kraken",
        base_symbol="BTC",
        quote_symbol="USD",
        interval="1h",
        now=third.close_time + timedelta(minutes=2),
    )

    assert [candle.open_time for candle in validated] == [first.open_time, third.open_time]
    assert [diagnostic.code for diagnostic in diagnostics] == ["duplicate_candle", "candle_gap"]
    assert diagnostics[1].severity == "warning"


@pytest.mark.parametrize(
    ("batch", "now", "expected_code"),
    [
        (
            [make_candle(), make_candle(close="102", high="103", low="101")],
            START + timedelta(hours=2),
            "conflicting_duplicate",
        ),
        (
            [
                make_candle(start=START, close="100"),
                make_candle(
                    start=START + timedelta(hours=1),
                    close="180",
                    high="181",
                    low="179",
                ),
            ],
            START + timedelta(hours=2),
            "price_change_outlier",
        ),
        (
            [make_candle(start=START - timedelta(hours=8))],
            START,
            "stale_candles",
        ),
    ],
)
def test_validator_rejects_bad_batches_with_diagnostics(
    batch: list[VenueCandle],
    now: datetime,
    expected_code: str,
) -> None:
    with pytest.raises(CandleIngestionError) as error:
        CandleBatchValidator().validate(
            batch,
            venue="kraken",
            base_symbol="BTC",
            quote_symbol="USD",
            interval="1h",
            now=now,
        )

    assert expected_code in {diagnostic.code for diagnostic in error.value.diagnostics}
    assert all(diagnostic.message for diagnostic in error.value.diagnostics)


def test_ingestion_upserts_identical_runs_without_duplicate_candles() -> None:
    repository, engine = make_repository()
    batch = [make_candle(), make_candle(start=START + timedelta(hours=1), is_complete=False)]
    service = CandleIngestionService(
        repository,
        clock=lambda: START + timedelta(hours=1, minutes=5),
    )
    provider = FixtureProvider(batch)

    first_run = service.ingest(
        provider,
        base_symbol="BTC",
        quote_symbol="USD",
        interval="1h",
    )
    second_run = service.ingest(
        provider,
        base_symbol="BTC",
        quote_symbol="USD",
        interval="1h",
    )

    with engine.connect() as connection:
        count = connection.execute(candles.select().with_only_columns(candles.c.id)).all()
        runs = connection.execute(ingestion_runs.select()).mappings().all()
        health = connection.execute(provider_health.select()).mappings().one()

    assert UUID(str(first_run["run_id"])) != UUID(str(second_run["run_id"]))
    assert first_run["upserted_count"] == second_run["upserted_count"] == 2
    assert len(count) == 2
    assert len(runs) == 2
    assert all(run["status"] == "succeeded" for run in runs)
    assert health["status"] == "healthy"
    assert health["last_success_at"] is not None
    engine.dispose()


def test_failed_ingestion_persists_provider_health_and_preserves_last_success() -> None:
    repository, engine = make_repository()
    service = CandleIngestionService(
        repository,
        clock=lambda: START + timedelta(hours=1, minutes=5),
    )
    service.ingest(
        FixtureProvider([make_candle()]),
        base_symbol="BTC",
        quote_symbol="USD",
        interval="1h",
    )
    with engine.connect() as connection:
        previous_success = (
            connection.execute(provider_health.select()).mappings().one()["last_success_at"]
        )

    with pytest.raises(RuntimeError, match="provider unavailable"):
        service.ingest(
            FixtureProvider(error=RuntimeError("provider unavailable")),
            base_symbol="BTC",
            quote_symbol="USD",
            interval="1h",
        )

    with engine.connect() as connection:
        failed_run = (
            connection.execute(ingestion_runs.select().where(ingestion_runs.c.status == "failed"))
            .mappings()
            .one()
        )
        health = connection.execute(provider_health.select()).mappings().one()

    assert failed_run["error_message"] == "provider unavailable"
    assert failed_run["diagnostics"][0]["code"] == "ingestion_failed"
    assert health["status"] == "degraded"
    assert health["last_error"] == "provider unavailable"
    assert health["last_success_at"] == previous_success
    engine.dispose()


def test_data_health_endpoint_returns_freshness_and_failed_runs() -> None:
    repository, engine = make_repository()
    service = CandleIngestionService(
        repository,
        clock=lambda: START + timedelta(hours=1, minutes=5),
    )
    service.ingest(
        FixtureProvider([make_candle()]),
        base_symbol="BTC",
        quote_symbol="USD",
        interval="1h",
    )
    with pytest.raises(RuntimeError):
        service.ingest(
            FixtureProvider(error=RuntimeError("temporary provider failure")),
            base_symbol="BTC",
            quote_symbol="USD",
            interval="1h",
        )

    app.dependency_overrides[get_candle_repository] = lambda: repository
    try:
        response = TestClient(app).get("/api/v1/data-health")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 200
    body = response.json()
    assert body["providers"][0]["status"] == "degraded"
    assert body["providers"][0]["last_success_at"] is not None
    assert body["freshness"][0]["venue_pair"] == "XBT/USD"
    assert body["freshness"][0]["candle_count"] == 1
    assert body["recent_failed_runs"][0]["error_message"] == "temporary provider failure"


def test_ingestion_endpoint_fetches_and_persists_configured_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, engine = make_repository()
    app.dependency_overrides[get_candle_repository] = lambda: repository
    monkeypatch.setattr(
        main,
        "create_venue_market_data_provider",
        lambda settings: FixtureProvider(
            [
                make_candle(
                    start=datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
                    - timedelta(hours=1)
                )
            ]
        ),
    )
    try:
        response = TestClient(app).post(
            "/api/v1/candles/ingest",
            json={
                "base_symbol": "BTC",
                "quote_symbol": "USD",
                "interval": "1h",
            },
        )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"
    assert response.json()["pair"] == "XBT/USD"
    assert response.json()["upserted_count"] == 1


def test_ingestion_endpoint_returns_diagnostics_for_stale_candles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository, engine = make_repository()
    stale = make_candle(start=START - timedelta(hours=8))
    app.dependency_overrides[get_candle_repository] = lambda: repository
    monkeypatch.setattr(
        main,
        "create_venue_market_data_provider",
        lambda settings: FixtureProvider([stale]),
    )
    try:
        response = TestClient(app).post(
            "/api/v1/candles/ingest",
            json={
                "base_symbol": "BTC",
                "quote_symbol": "USD",
                "interval": "1h",
            },
        )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 422
    assert response.json()["detail"]["diagnostics"][0]["code"] == "stale_candles"
