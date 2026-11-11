"""FastAPI application entry point."""

from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from crypto_market_insights.candle_ingestion import (
    CandleIngestionError,
    CandleIngestionService,
)
from crypto_market_insights.candle_storage import CandleRepository
from crypto_market_insights.config import get_settings
from crypto_market_insights.dependencies import get_candle_repository
from crypto_market_insights.health import health_check
from crypto_market_insights.kraken import (
    VenueMarketDataError,
    create_venue_market_data_provider,
)

app = FastAPI(title="Crypto Market Insights API")


class CandleIngestionRequest(BaseModel):
    """Validated request to ingest one configured venue pair and interval."""

    model_config = ConfigDict(extra="forbid")

    base_symbol: str = Field(min_length=2, max_length=20, pattern=r"^[A-Za-z0-9]+$")
    quote_symbol: str = Field(min_length=2, max_length=20, pattern=r"^[A-Za-z0-9]+$")
    interval: str = Field(min_length=2, max_length=16)
    since: datetime | None = None

    @field_validator("since")
    @classmethod
    def since_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("since must include a timezone.")
        return value


class CandleIngestionResponse(BaseModel):
    run_id: UUID
    venue: str
    pair: str
    interval: str
    status: str
    received_count: int
    upserted_count: int
    diagnostics: list[dict[str, Any]]


class ProviderHealthResponse(BaseModel):
    venue: str
    status: str
    last_attempt_at: datetime
    last_success_at: datetime | None
    last_error: str | None
    last_run_id: UUID


class CandleFreshnessResponse(BaseModel):
    venue: str
    venue_pair: str
    interval: str
    latest_close_time: datetime
    last_retrieved_at: datetime
    candle_count: int


class FailedIngestionResponse(BaseModel):
    id: UUID
    venue: str
    venue_pair: str
    interval: str
    status: str
    started_at: datetime
    completed_at: datetime | None
    received_count: int
    upserted_count: int
    diagnostics: list[dict[str, Any]]
    error_message: str | None


class DataHealthResponse(BaseModel):
    providers: list[ProviderHealthResponse]
    freshness: list[CandleFreshnessResponse]
    recent_failed_runs: list[FailedIngestionResponse]


@app.get("/health")
def get_health() -> dict[str, str]:
    """Return API readiness status."""
    return health_check()


@app.post("/api/v1/candles/ingest", response_model=CandleIngestionResponse)
def ingest_candles(
    request: CandleIngestionRequest,
    repository: Annotated[CandleRepository, Depends(get_candle_repository)],
) -> dict[str, Any]:
    """Fetch, validate, and upsert one supported pair's candle batch."""
    settings = get_settings()
    provider = create_venue_market_data_provider(settings)
    try:
        service = CandleIngestionService(repository)
        try:
            return service.ingest(
                provider,
                base_symbol=request.base_symbol,
                quote_symbol=request.quote_symbol,
                interval=request.interval,
                since=request.since,
            )
        except CandleIngestionError as error:
            raise HTTPException(
                status_code=422,
                detail={
                    "message": str(error),
                    "diagnostics": [
                        diagnostic.model_dump(mode="json") for diagnostic in error.diagnostics
                    ],
                },
            ) from error
        except VenueMarketDataError as error:
            raise HTTPException(
                status_code=502,
                detail={
                    "message": str(error),
                    "venue": error.venue,
                    "operation": error.operation,
                    "attempts": error.attempts,
                    "status_code": error.status_code,
                    "failed_at": error.failed_at.isoformat(),
                    "retryable": error.retryable,
                },
            ) from error
    finally:
        provider.close()


@app.get("/api/v1/data-health", response_model=DataHealthResponse)
def get_data_health(
    repository: Annotated[CandleRepository, Depends(get_candle_repository)],
) -> dict[str, Any]:
    """Expose venue provider state, candle freshness, and recent failed runs."""
    result = repository.get_data_health()
    return {
        "providers": result["providers"],
        "freshness": [
            {
                **row,
                "latest_close_time": _to_utc(row["latest_close_time"]),
                "last_retrieved_at": _to_utc(row["last_retrieved_at"]),
            }
            for row in result["freshness"]
        ],
        "recent_failed_runs": [
            {
                **row,
                "started_at": _to_utc(row["started_at"]),
                "completed_at": (_to_utc(row["completed_at"]) if row["completed_at"] else None),
            }
            for row in result["recent_failed_runs"]
        ],
    }


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
