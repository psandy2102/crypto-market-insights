"""Reusable FastAPI dependencies."""

from functools import lru_cache

from crypto_market_insights.candle_storage import CandleRepository, create_database_engine
from crypto_market_insights.config import get_settings
from crypto_market_insights.risk_storage import RiskDecisionRepository
from crypto_market_insights.universe_storage import UniverseRepository


@lru_cache
def get_candle_repository() -> CandleRepository:
    """Return the process-wide candle repository."""
    settings = get_settings()
    return CandleRepository(create_database_engine(settings.database_url))


@lru_cache
def get_universe_repository() -> UniverseRepository:
    """Return the process-wide point-in-time universe repository."""
    settings = get_settings()
    return UniverseRepository(create_database_engine(settings.database_url))


@lru_cache
def get_risk_decision_repository() -> RiskDecisionRepository:
    """Return the process-wide risk-gate decision repository."""
    settings = get_settings()
    return RiskDecisionRepository(create_database_engine(settings.database_url))
