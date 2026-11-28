"""Reusable FastAPI dependencies."""

from functools import lru_cache

from crypto_market_insights.candle_storage import CandleRepository, create_database_engine
from crypto_market_insights.config import get_settings
from crypto_market_insights.llm_storage import LlmSummaryRepository
from crypto_market_insights.llm_summaries import (
    GroundedSummaryService,
    OllamaProvider,
)
from crypto_market_insights.news_storage import NewsRepository
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


@lru_cache
def get_news_repository() -> NewsRepository:
    """Return the process-wide RSS news repository."""
    settings = get_settings()
    return NewsRepository(create_database_engine(settings.database_url))


@lru_cache
def get_llm_summary_service() -> GroundedSummaryService:
    """Return the process-wide source-grounded summary service."""
    settings = get_settings()
    parameters = {
        "temperature": settings.ollama_temperature,
        "top_p": settings.ollama_top_p,
        "seed": settings.ollama_seed,
        "num_predict": settings.ollama_num_predict,
    }
    return GroundedSummaryService(
        get_news_repository(),
        LlmSummaryRepository(create_database_engine(settings.database_url)),
        OllamaProvider(settings.ollama_base_url),
        model=settings.ollama_model,
        generation_parameters=parameters,
    )
