"""Provider-independent venue market data contracts."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class VenueCandle(BaseModel):
    """Validated OHLCV candle from one explicitly identified venue and pair."""

    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    venue: str = Field(min_length=1)
    venue_pair: str = Field(min_length=1)
    base_symbol: str = Field(min_length=1)
    quote_symbol: str = Field(min_length=1)
    interval: str = Field(min_length=1)
    open_time: datetime
    close_time: datetime
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    volume: Decimal = Field(ge=0)
    is_complete: bool
    source_timestamp: datetime
    retrieved_at: datetime

    @field_validator("open_time", "close_time", "source_timestamp", "retrieved_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timestamp must include a timezone.")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_ohlc_and_times(self) -> "VenueCandle":
        if self.close_time <= self.open_time:
            raise ValueError("close_time must be after open_time.")
        if (
            self.high < self.low
            or self.high < max(self.open, self.close)
            or self.low > min(self.open, self.close)
        ):
            raise ValueError("Candle high and low must contain open and close.")
        return self


class VenueMarketSnapshot(BaseModel):
    """Ticker values reported by the selected venue, never an aggregator."""

    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    venue: str = Field(min_length=1)
    venue_pair: str = Field(min_length=1)
    base_symbol: str = Field(min_length=1)
    quote_symbol: str = Field(min_length=1)
    last_price: Decimal = Field(gt=0)
    best_bid: Decimal = Field(gt=0)
    best_ask: Decimal = Field(gt=0)
    volume_today: Decimal = Field(ge=0)
    volume_24h: Decimal = Field(ge=0)
    source_timestamp: datetime
    retrieved_at: datetime

    @field_validator("source_timestamp", "retrieved_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Timestamp must include a timezone.")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_market(self) -> "VenueMarketSnapshot":
        if self.best_ask < self.best_bid:
            raise ValueError("best_ask must not be below best_bid.")
        return self


class VenueMarketDataProvider(Protocol):
    """Interface implemented by public exchange market-data providers."""

    venue_name: str

    def fetch_candles(
        self,
        *,
        base_symbol: str,
        quote_symbol: str,
        interval: str,
        since: datetime | None = None,
    ) -> list[VenueCandle]:
        """Fetch venue-specific candles for one unambiguous spot pair."""

    def fetch_market_snapshot(
        self,
        *,
        base_symbol: str,
        quote_symbol: str,
    ) -> VenueMarketSnapshot:
        """Fetch venue-specific ticker data for one unambiguous spot pair."""

    def close(self) -> None:
        """Release provider resources."""
