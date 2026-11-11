"""Kraken public spot market-data adapter."""

import json
import logging
import math
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from crypto_market_insights.config import Settings
from crypto_market_insights.market_data import VenueCandle, VenueMarketSnapshot

LOGGER = logging.getLogger(__name__)
API_BASE_URL = "https://api.kraken.com/0"
INTERVAL_MINUTES: dict[str, int] = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
    "1w": 10080,
    "15d": 21600,
}
SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]{2,20}$")
ASSET_ALIASES = {
    "XXBT": "BTC",
    "XBT": "BTC",
    "XETH": "ETH",
    "ZUSD": "USD",
    "ZEUR": "EUR",
    "ZGBP": "GBP",
    "ZJPY": "JPY",
    "ZCAD": "CAD",
    "ZAUD": "AUD",
    "ZCHF": "CHF",
}


class VenueMarketDataError(RuntimeError):
    """Visible exchange request, pair-resolution, or response failure."""

    def __init__(
        self,
        message: str,
        *,
        operation: str,
        attempts: int = 0,
        failed_at: datetime | None = None,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        timestamp = failed_at or datetime.now(UTC)
        super().__init__(
            f"{message} [venue=kraken, operation={operation}, attempts={attempts}, "
            f"status_code={status_code}, failed_at={timestamp.isoformat()}, "
            f"retryable={retryable}]"
        )
        self.venue = "kraken"
        self.operation = operation
        self.attempts = attempts
        self.failed_at = timestamp
        self.status_code = status_code
        self.retryable = retryable


class KrakenPairRecord(BaseModel):
    """Fields used to resolve one Kraken tradable pair."""

    model_config = ConfigDict(extra="ignore")

    altname: str = Field(min_length=1)
    wsname: str | None = None
    base: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    status: str


class KrakenEnvelope(BaseModel):
    """Common Kraken REST response envelope."""

    model_config = ConfigDict(extra="ignore")

    error: list[str]
    result: dict[str, Any]


class KrakenOhlcRow(BaseModel):
    """One OHLC row in Kraken's positional response format."""

    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)

    time: Decimal
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    vwap: Decimal = Field(ge=0)
    volume: Decimal = Field(ge=0)
    count: int = Field(ge=0)

    @model_validator(mode="before")
    @classmethod
    def map_kraken_array(cls, value: object) -> object:
        if not isinstance(value, list) or len(value) != 8:
            raise ValueError("Kraken OHLC rows must contain exactly eight values.")
        return dict(
            zip(
                ("time", "open", "high", "low", "close", "vwap", "volume", "count"),
                value,
                strict=True,
            )
        )


class KrakenTickerRecord(BaseModel):
    """Ticker subset returned by Kraken's public Ticker endpoint."""

    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)

    ask: list[Decimal] = Field(validation_alias=AliasChoices("a", "ask"), min_length=2)
    bid: list[Decimal] = Field(validation_alias=AliasChoices("b", "bid"), min_length=2)
    close: list[Decimal] = Field(validation_alias=AliasChoices("c", "close"), min_length=2)
    volume: list[Decimal] = Field(validation_alias=AliasChoices("v", "volume"), min_length=2)


def _normalize_asset_code(code: str) -> str:
    normalized = code.strip().upper()
    return ASSET_ALIASES.get(normalized, normalized)


def _as_utc_datetime(epoch: Decimal) -> datetime:
    if not epoch.is_finite():
        raise ValueError("Provider timestamp must be finite.")
    whole_seconds = int(epoch)
    fractional_microseconds = int((epoch - whole_seconds) * Decimal(1_000_000))
    return datetime.fromtimestamp(whole_seconds, tz=UTC) + timedelta(
        microseconds=fractional_microseconds
    )


class KrakenMarketDataProvider:
    """Fetch OHLCV and ticker data only from Kraken public endpoints."""

    venue_name = "kraken"

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        max_attempts: int = 3,
        retry_base_delay: float = 1.0,
        max_retry_delay: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1.")
        if retry_base_delay < 0 or max_retry_delay < 0:
            raise ValueError("Retry delays cannot be negative.")
        self._client = client or httpx.Client(
            base_url=API_BASE_URL,
            timeout=httpx.Timeout(15.0),
        )
        self._owns_client = client is None
        self._max_attempts = max_attempts
        self._retry_base_delay = retry_base_delay
        self._max_retry_delay = max_retry_delay
        self._sleep = sleep

    def close(self) -> None:
        """Close the HTTP client when this provider created it."""
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "KrakenMarketDataProvider":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def fetch_candles(
        self,
        *,
        base_symbol: str,
        quote_symbol: str,
        interval: str,
        since: datetime | None = None,
    ) -> list[VenueCandle]:
        """Fetch and validate candles for one exact base/quote mapping."""
        if interval not in INTERVAL_MINUTES:
            raise ValueError(f"Unsupported Kraken candle interval: {interval}")
        if since is not None:
            self._require_aware(since, "since")
            if since.timestamp() < 0:
                raise ValueError("since must not be before the Unix epoch.")

        pair = self._resolve_pair(base_symbol=base_symbol, quote_symbol=quote_symbol)
        params: dict[str, str | int] = {
            "pair": pair.altname,
            "interval": INTERVAL_MINUTES[interval],
        }
        if since is not None:
            params["since"] = int(since.timestamp())
        payload = self._get_json("/public/OHLC", params=params, operation="fetch_candles")
        try:
            envelope = KrakenEnvelope.model_validate(payload)
            self._raise_for_exchange_errors(envelope.error, "fetch_candles")
            keys = [key for key in envelope.result if key != "last"]
            if len(keys) != 1:
                raise ValueError("Kraken OHLC response must contain exactly one pair.")
            rows = TypeAdapter(list[KrakenOhlcRow]).validate_python(envelope.result[keys[0]])
        except (ValidationError, ValueError, TypeError) as error:
            raise self._response_error(
                "Kraken returned invalid OHLC data.",
                "fetch_candles",
            ) from error

        retrieved_at = datetime.now(UTC)
        base = _normalize_asset_code(base_symbol)
        quote = _normalize_asset_code(quote_symbol)
        duration = timedelta(minutes=INTERVAL_MINUTES[interval])
        candles: list[VenueCandle] = []
        try:
            for index, row in enumerate(rows):
                open_time = _as_utc_datetime(row.time)
                close_time = open_time + duration
                candles.append(
                    VenueCandle(
                        venue=self.venue_name,
                        venue_pair=pair.wsname or pair.altname,
                        base_symbol=base,
                        quote_symbol=quote,
                        interval=interval,
                        open_time=open_time,
                        close_time=close_time,
                        open=row.open,
                        high=row.high,
                        low=row.low,
                        close=row.close,
                        volume=row.volume,
                        is_complete=index < len(rows) - 1,
                        source_timestamp=close_time,
                        retrieved_at=retrieved_at,
                    )
                )
        except (ValidationError, ValueError, OverflowError) as error:
            raise self._response_error(
                "Kraken returned invalid normalized candle data.",
                "fetch_candles",
            ) from error
        return candles

    def fetch_market_snapshot(
        self,
        *,
        base_symbol: str,
        quote_symbol: str,
    ) -> VenueMarketSnapshot:
        """Fetch a ticker snapshot from Kraken for the resolved venue pair."""
        pair = self._resolve_pair(base_symbol=base_symbol, quote_symbol=quote_symbol)
        payload = self._get_json(
            "/public/Ticker",
            params={"pair": pair.altname},
            operation="fetch_market_snapshot",
        )
        try:
            envelope = KrakenEnvelope.model_validate(payload)
            self._raise_for_exchange_errors(envelope.error, "fetch_market_snapshot")
            if len(envelope.result) != 1:
                raise ValueError("Kraken ticker response must contain exactly one pair.")
            record = KrakenTickerRecord.model_validate(next(iter(envelope.result.values())))
            last_price, bid, ask = record.close[0], record.bid[0], record.ask[0]
            volume_today, volume_24h = record.volume[:2]
            retrieved_at = datetime.now(UTC)
            return VenueMarketSnapshot(
                venue=self.venue_name,
                venue_pair=pair.wsname or pair.altname,
                base_symbol=_normalize_asset_code(base_symbol),
                quote_symbol=_normalize_asset_code(quote_symbol),
                last_price=last_price,
                best_bid=bid,
                best_ask=ask,
                volume_today=volume_today,
                volume_24h=volume_24h,
                source_timestamp=retrieved_at,
                retrieved_at=retrieved_at,
            )
        except (ValidationError, ValueError, TypeError) as error:
            raise self._response_error(
                "Kraken returned invalid ticker data.",
                "fetch_market_snapshot",
            ) from error

    def _resolve_pair(self, *, base_symbol: str, quote_symbol: str) -> KrakenPairRecord:
        base = _normalize_asset_code(base_symbol)
        quote = _normalize_asset_code(quote_symbol)
        self._validate_symbol(base, "base_symbol")
        self._validate_symbol(quote, "quote_symbol")
        if not base or not quote or base == quote:
            raise ValueError("A distinct base and quote symbol are required.")

        payload = self._get_json("/public/AssetPairs", params={}, operation="resolve_pair")
        try:
            envelope = KrakenEnvelope.model_validate(payload)
            self._raise_for_exchange_errors(envelope.error, "resolve_pair")
            pairs = TypeAdapter(dict[str, KrakenPairRecord]).validate_python(envelope.result)
        except (ValidationError, ValueError, TypeError) as error:
            raise self._response_error(
                "Kraken returned invalid pair data.",
                "resolve_pair",
            ) from error

        matching = [pair for pair in pairs.values() if self._pair_symbols(pair) == (base, quote)]
        if not matching:
            raise VenueMarketDataError(
                f"Kraken spot pair {base}/{quote} is unavailable.",
                operation="resolve_pair",
            )
        if len(matching) > 1:
            raise VenueMarketDataError(
                f"Kraken spot pair {base}/{quote} is ambiguous ({len(matching)} mappings).",
                operation="resolve_pair",
            )
        pair = matching[0]
        if pair.status.lower() != "online":
            raise VenueMarketDataError(
                f"Kraken spot pair {base}/{quote} is not online (status={pair.status}).",
                operation="resolve_pair",
            )
        return pair

    @staticmethod
    def _pair_symbols(pair: KrakenPairRecord) -> tuple[str, str]:
        if pair.wsname and "/" in pair.wsname:
            base_symbol, quote_symbol = pair.wsname.split("/", maxsplit=1)
        else:
            base_symbol, quote_symbol = pair.base, pair.quote
        return _normalize_asset_code(base_symbol), _normalize_asset_code(quote_symbol)

    @staticmethod
    def _validate_symbol(symbol: str, field_name: str) -> None:
        if not SYMBOL_PATTERN.fullmatch(symbol):
            raise ValueError(f"{field_name} must be a simple asset symbol.")

    def _get_json(
        self,
        path: str,
        *,
        params: dict[str, str | int],
        operation: str,
    ) -> object:
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._client.get(f"{API_BASE_URL}{path}", params=params)
            except httpx.TransportError as error:
                if attempt < self._max_attempts:
                    delay = min(
                        self._retry_base_delay * (2 ** (attempt - 1)),
                        self._max_retry_delay,
                    )
                    LOGGER.warning(
                        "Retrying transient Kraken market-data request failure",
                        extra={
                            "venue": self.venue_name,
                            "operation": operation,
                            "attempt": attempt,
                            "retry_delay_seconds": delay,
                        },
                    )
                    self._sleep(delay)
                    continue
                provider_error = self._request_error(
                    "Kraken request failed after transient network errors.",
                    operation=operation,
                    attempts=attempt,
                    retryable=True,
                )
                LOGGER.error("%s", provider_error, extra=self._log_context(provider_error))
                raise provider_error from error

            if response.status_code == 429 or 500 <= response.status_code < 600:
                retry_delay = (
                    self._retry_delay(response, attempt) if attempt < self._max_attempts else None
                )
                if retry_delay is not None:
                    LOGGER.warning(
                        "Retrying transient Kraken market-data response",
                        extra={
                            "venue": self.venue_name,
                            "operation": operation,
                            "attempt": attempt,
                            "status_code": response.status_code,
                            "retry_delay_seconds": retry_delay,
                        },
                    )
                    self._sleep(retry_delay)
                    continue
                provider_error = self._request_error(
                    "Kraken request exhausted retries or exceeded the retry wait limit.",
                    operation=operation,
                    attempts=attempt,
                    status_code=response.status_code,
                    retryable=True,
                )
                LOGGER.error("%s", provider_error, extra=self._log_context(provider_error))
                raise provider_error
            if response.is_error:
                provider_error = self._request_error(
                    "Kraken rejected the public market-data request.",
                    operation=operation,
                    attempts=attempt,
                    status_code=response.status_code,
                    retryable=False,
                )
                LOGGER.error("%s", provider_error, extra=self._log_context(provider_error))
                raise provider_error
            try:
                return json.loads(response.content, parse_float=Decimal)
            except (json.JSONDecodeError, UnicodeDecodeError) as error:
                provider_error = self._response_error(
                    "Kraken returned invalid JSON.",
                    operation,
                    attempts=attempt,
                    status_code=response.status_code,
                )
                LOGGER.error("%s", provider_error, extra=self._log_context(provider_error))
                raise provider_error from error

        raise RuntimeError("Kraken request loop exited unexpectedly.")

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float | None:
        retry_after = response.headers.get("Retry-After")
        if retry_after is None:
            return min(
                self._retry_base_delay * (2 ** (attempt - 1)),
                self._max_retry_delay,
            )
        try:
            delay = float(retry_after)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(retry_after)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=UTC)
                delay = (retry_at.astimezone(UTC) - datetime.now(UTC)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                delay = self._retry_base_delay * (2 ** (attempt - 1))
        if not math.isfinite(delay):
            delay = self._retry_base_delay * (2 ** (attempt - 1))
        if delay > self._max_retry_delay:
            return None
        return max(delay, 0)

    @staticmethod
    def _require_aware(value: datetime, field_name: str) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field_name} must include a timezone.")

    @staticmethod
    def _raise_for_exchange_errors(errors: list[str], operation: str) -> None:
        if errors:
            raise VenueMarketDataError(
                f"Kraken returned exchange errors: {', '.join(errors)}",
                operation=operation,
            )

    @staticmethod
    def _request_error(
        message: str,
        *,
        operation: str,
        attempts: int,
        retryable: bool,
        status_code: int | None = None,
    ) -> VenueMarketDataError:
        return VenueMarketDataError(
            message,
            operation=operation,
            attempts=attempts,
            status_code=status_code,
            retryable=retryable,
        )

    @staticmethod
    def _response_error(
        message: str,
        operation: str,
        *,
        attempts: int = 1,
        status_code: int | None = None,
    ) -> VenueMarketDataError:
        return VenueMarketDataError(
            message,
            operation=operation,
            attempts=attempts,
            status_code=status_code,
            retryable=False,
        )

    @staticmethod
    def _log_context(error: VenueMarketDataError) -> dict[str, object]:
        return {
            "venue": error.venue,
            "operation": error.operation,
            "attempts": error.attempts,
            "failed_at": error.failed_at.isoformat(),
            "status_code": error.status_code,
            "retryable": error.retryable,
        }


def create_venue_market_data_provider(
    settings: Settings,
    *,
    client: httpx.Client | None = None,
) -> KrakenMarketDataProvider:
    """Construct the explicitly configured venue adapter."""
    if settings.market_data_venue.lower() != KrakenMarketDataProvider.venue_name:
        raise ValueError(f"Unsupported market-data venue: {settings.market_data_venue}")
    return KrakenMarketDataProvider(client=client)
