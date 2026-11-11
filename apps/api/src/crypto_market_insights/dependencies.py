"""Reusable FastAPI dependencies."""

from functools import lru_cache

from crypto_market_insights.candle_storage import CandleRepository, create_database_engine
from crypto_market_insights.config import get_settings


@lru_cache
def get_candle_repository() -> CandleRepository:
    """Return the process-wide candle repository."""
    settings = get_settings()
    return CandleRepository(create_database_engine(settings.database_url))
