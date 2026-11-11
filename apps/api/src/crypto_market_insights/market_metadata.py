"""Provider-independent market metadata contracts."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AssetMarketMetadata(BaseModel):
    """Validated market metadata with source and retrieval provenance."""

    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    provider: str = Field(min_length=1)
    provider_asset_id: str = Field(min_length=1)
    canonical_asset_id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    name: str = Field(min_length=1)
    current_price: Decimal | None = Field(default=None, gt=0)
    market_cap: Decimal | None = Field(default=None, ge=0)
    market_cap_rank: int | None = Field(default=None, gt=0)
    total_volume: Decimal | None = Field(default=None, ge=0)
    source_timestamp: datetime
    retrieved_at: datetime

    @field_validator("source_timestamp", "retrieved_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timestamp must include a timezone.")
        return value.astimezone(UTC)


class MarketMetadataProvider(Protocol):
    """Interface implemented by aggregator market metadata providers."""

    provider_name: str

    def fetch_markets(
        self,
        *,
        quote_currency: str,
        page: int = 1,
        per_page: int = 100,
    ) -> list[AssetMarketMetadata]:
        """Return one page of validated metadata ordered by market capitalization."""

    def close(self) -> None:
        """Release provider resources."""
