"""Environment-backed application settings."""

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
        default="postgresql://localhost:5432/crypto_insights",
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


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
