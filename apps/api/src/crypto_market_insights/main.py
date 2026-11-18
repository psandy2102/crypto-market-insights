"""FastAPI application entry point."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
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
from crypto_market_insights.dependencies import (
    get_candle_repository,
    get_risk_decision_repository,
    get_universe_repository,
)
from crypto_market_insights.health import health_check
from crypto_market_insights.kraken import (
    VenueMarketDataError,
    create_venue_market_data_provider,
)
from crypto_market_insights.risk_gates import (
    RiskGateEvaluator,
    RiskGateInput,
    RiskGatePolicy,
)
from crypto_market_insights.risk_storage import RiskDecisionRepository
from crypto_market_insights.universe_storage import UniverseRepository

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


class UniverseRunResponse(BaseModel):
    id: UUID
    evaluated_at: datetime
    venue: str
    quote_currency: str
    metadata_provider: str
    universe_version: str
    ranking_strategy_version: str
    requested_size: int
    candidate_count: int
    selected_count: int
    no_trade: bool
    ranking_weights: dict[str, float]


class UniverseCandidateResponse(BaseModel):
    provider_asset_id: str
    canonical_asset_id: str
    symbol: str
    name: str
    venue_pair: str | None
    asset_types: list[str]
    history_timeframe: str
    market_cap: Decimal | None
    quote_volume: Decimal | None
    metadata_source_timestamp: datetime
    metadata_retrieved_at: datetime
    history_candle_count: int
    history_as_of: datetime | None
    data_quality_score: Decimal | None
    eligible: bool
    selected: bool
    selection_rank: int | None
    exclusion_reasons: list[str]
    effective_from: datetime | None
    effective_to: datetime | None


class UniverseRankingResponse(BaseModel):
    provider_asset_id: str
    canonical_asset_id: str
    symbol: str
    venue_pair: str
    strategy_version: str
    component_scores: dict[str, float] | None
    total_score: float | None
    rank: int | None
    gate_failures: list[str]


class LatestUniverseResponse(BaseModel):
    run: UniverseRunResponse
    candidates: list[UniverseCandidateResponse]
    rankings: list[UniverseRankingResponse]


class RiskGateReasonResponse(BaseModel):
    code: str
    message: str


class RiskGateDecisionResponse(BaseModel):
    candidate_asset_id: str
    strategy_version: str
    outcome: str
    approved: bool
    reasons: list[RiskGateReasonResponse]
    evaluated_at: datetime
    expires_at: datetime
    post_cost_reward_risk: Decimal | None


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


@app.get("/api/v1/universe/latest", response_model=LatestUniverseResponse)
def get_latest_universe(
    repository: Annotated[UniverseRepository, Depends(get_universe_repository)],
    venue: str | None = None,
) -> dict[str, Any]:
    """Expose the latest point-in-time membership and component-level rankings."""
    result = repository.get_latest(venue=venue)
    if result is None:
        raise HTTPException(status_code=404, detail="No universe snapshot is available.")
    result["run"]["ranking_weights"] = {
        key: float(value) for key, value in result["run"]["ranking_weights"].items()
    }
    for ranking in result["rankings"]:
        if ranking["component_scores"] is not None:
            ranking["component_scores"] = {
                key: float(value) for key, value in ranking["component_scores"].items()
            }
        if ranking["total_score"] is not None:
            ranking["total_score"] = float(ranking["total_score"])
    return result


@app.post("/api/v1/risk-gates/evaluate", response_model=RiskGateDecisionResponse)
def evaluate_risk_gate(
    inputs: RiskGateInput,
    repository: Annotated[
        RiskDecisionRepository,
        Depends(get_risk_decision_repository),
    ],
) -> dict[str, Any]:
    """Persist and return an explicit TRADE or NO_TRADE risk decision."""
    settings = get_settings()
    policy = RiskGatePolicy(
        max_candle_age=timedelta(hours=settings.risk_max_candle_age_hours),
        min_quote_volume=settings.risk_min_quote_volume,
        min_liquidity_score=settings.risk_min_liquidity_score,
        max_atr_to_close=settings.risk_max_atr_to_close,
        min_post_cost_reward_risk=settings.risk_min_post_cost_reward_risk,
        setup_expiry=timedelta(hours=settings.risk_setup_expiry_hours),
    )
    result = RiskGateEvaluator(policy).evaluate(inputs)
    repository.persist(result)
    return result.model_dump(mode="python")


@app.get("/api/v1/risk-gates/latest", response_model=dict[str, Any])
def get_latest_risk_decision(
    repository: Annotated[
        RiskDecisionRepository,
        Depends(get_risk_decision_repository),
    ],
    candidate_asset_id: str | None = None,
) -> dict[str, Any]:
    """Return the latest persisted TRADE or NO_TRADE risk decision."""
    result = repository.get_latest(candidate_asset_id=candidate_asset_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No risk decision is available.")
    return result


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
