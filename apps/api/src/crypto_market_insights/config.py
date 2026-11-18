"""Environment-backed application settings."""

from decimal import Decimal
from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables or .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_timezone: str = "America/Toronto"
    database_url: str = Field(
        default="postgresql+psycopg://localhost:5432/crypto_insights",
        repr=False,
    )
    market_metadata_provider: str = Field(default="coingecko", min_length=1)
    market_data_venue: str = "kraken"
    default_quote_currency: str = "USD"
    coingecko_api_key: SecretStr | None = Field(default=None, repr=False)
    llm_provider: str = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = ""
    daily_analysis_time: str = "08:00"
    universe_size: int = 10
    universe_min_market_cap: Decimal = Decimal("100000000")
    universe_min_quote_volume: Decimal = Decimal("10000000")
    universe_min_history_candles: int = 200
    universe_history_timeframe: str = "1d"
    universe_max_metadata_age_hours: int = 24
    universe_max_history_age_hours: int = 26
    universe_min_data_quality: Decimal = Decimal(90)
    risk_max_candle_age_hours: int = 26
    risk_min_quote_volume: Decimal = Decimal("10000000")
    risk_min_liquidity_score: Decimal = Decimal(60)
    risk_max_atr_to_close: Decimal = Decimal("0.20")
    risk_min_post_cost_reward_risk: Decimal = Decimal("1.50")
    risk_setup_expiry_hours: int = 24


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
