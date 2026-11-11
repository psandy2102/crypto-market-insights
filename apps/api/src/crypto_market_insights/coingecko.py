"""CoinGecko market metadata adapter."""

import json
import logging
import math
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from email.utils import parsedate_to_datetime

import httpx
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from crypto_market_insights.config import Settings
from crypto_market_insights.market_metadata import (
    AssetMarketMetadata,
    MarketMetadataProvider,
)

LOGGER = logging.getLogger(__name__)
API_URL = "https://api.coingecko.com/api/v3/coins/markets"
SUPPORTED_CURRENCY_PATTERN = re.compile(r"^[a-z0-9-]{2,20}$")
COIN_ID_PATTERN = re.compile(r"^[a-zA-Z0-9._-]{1,128}$")


class CoinGeckoMarketRecord(BaseModel):
    """Validated subset of a CoinGecko /coins/markets record."""

    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)

    id: str
    symbol: str
    name: str
    current_price: Decimal | None = None
    market_cap: Decimal | None = None
    market_cap_rank: int | None = None
    total_volume: Decimal | None = None
    last_updated: datetime


class MarketMetadataProviderError(RuntimeError):
    """A visible provider failure with request and retry provenance."""

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        operation: str,
        attempts: int,
        failed_at: datetime,
        status_code: int | None = None,
        retryable: bool,
    ) -> None:
        super().__init__(
            f"{message} [provider={provider}, operation={operation}, attempts={attempts}, "
            f"status_code={status_code}, failed_at={failed_at.isoformat()}, "
            f"retryable={retryable}]"
        )
        self.provider = provider
        self.operation = operation
        self.attempts = attempts
        self.failed_at = failed_at
        self.status_code = status_code
        self.retryable = retryable


class CoinGeckoResponseError(MarketMetadataProviderError):
    """CoinGecko returned invalid JSON or a response outside the schema."""


class CoinGeckoMarketMetadataProvider:
    """Fetch and normalize CoinGecko's paginated market-cap listing."""

    provider_name = "coingecko"

    def __init__(
        self,
        api_key: str | None = None,
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
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=httpx.Timeout(15.0))
        self._owns_client = client is None
        self._max_attempts = max_attempts
        self._retry_base_delay = retry_base_delay
        self._max_retry_delay = max_retry_delay
        self._sleep = sleep

    def close(self) -> None:
        """Close the HTTP client when this provider created it."""
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "CoinGeckoMarketMetadataProvider":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def fetch_markets(
        self,
        *,
        quote_currency: str,
        page: int = 1,
        per_page: int = 100,
    ) -> list[AssetMarketMetadata]:
        """Fetch, validate, and normalize a market-cap-ordered page."""
        normalized_currency = quote_currency.strip().lower()
        if not SUPPORTED_CURRENCY_PATTERN.fullmatch(normalized_currency):
            raise ValueError("quote_currency must be a supported currency code.")
        if page < 1:
            raise ValueError("page must be at least 1.")
        if not 1 <= per_page <= 250:
            raise ValueError("per_page must be between 1 and 250.")

        headers = {"x-cg-demo-api-key": self._api_key} if self._api_key else {}
        response, attempts = self._request(
            params={
                "vs_currency": normalized_currency,
                "order": "market_cap_desc",
                "per_page": per_page,
                "page": page,
                "sparkline": "false",
            },
            headers=headers,
        )
        retrieved_at = datetime.now(UTC)

        try:
            payload = json.loads(response.content, parse_float=Decimal)
            records = TypeAdapter(list[CoinGeckoMarketRecord]).validate_python(payload)
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, TypeError) as error:
            provider_error = CoinGeckoResponseError(
                "CoinGecko returned an invalid market metadata response.",
                provider=self.provider_name,
                operation="fetch_markets",
                attempts=attempts,
                failed_at=datetime.now(UTC),
                status_code=response.status_code,
                retryable=False,
            )
            self._log_failure("Market metadata response validation failed", provider_error, error)
            raise provider_error from error

        try:
            return [self._normalize(record, retrieved_at=retrieved_at) for record in records]
        except (ValueError, ValidationError) as error:
            provider_error = CoinGeckoResponseError(
                "CoinGecko returned market metadata that failed normalization.",
                provider=self.provider_name,
                operation="fetch_markets",
                attempts=attempts,
                failed_at=datetime.now(UTC),
                status_code=response.status_code,
                retryable=False,
            )
            self._log_failure("Market metadata normalization failed", provider_error, error)
            raise provider_error from error

    def _request(
        self,
        *,
        params: dict[str, str | int],
        headers: dict[str, str],
    ) -> tuple[httpx.Response, int]:
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._client.get(API_URL, params=params, headers=headers)
            except httpx.TransportError as error:
                if attempt < self._max_attempts:
                    delay = self._backoff_delay(attempt)
                    LOGGER.warning(
                        "Retrying transient market metadata request failure",
                        extra={
                            "provider": self.provider_name,
                            "operation": "fetch_markets",
                            "attempt": attempt,
                            "retry_delay_seconds": delay,
                        },
                    )
                    self._sleep(delay)
                    continue
                provider_error = self._request_error(
                    "CoinGecko request failed after transient network errors.",
                    attempts=attempt,
                    retryable=True,
                )
                self._log_failure("Market metadata provider request failed", provider_error, error)
                raise provider_error from error

            if response.status_code == 429 or 500 <= response.status_code < 600:
                if attempt < self._max_attempts:
                    retry_delay = self._retry_delay(response, attempt)
                    if retry_delay is not None:
                        LOGGER.warning(
                            "Retrying transient market metadata response",
                            extra={
                                "provider": self.provider_name,
                                "operation": "fetch_markets",
                                "attempt": attempt,
                                "status_code": response.status_code,
                                "retry_delay_seconds": retry_delay,
                            },
                        )
                        self._sleep(retry_delay)
                        continue
                provider_error = self._request_error(
                    "CoinGecko request exhausted retries or exceeded the retry wait limit.",
                    attempts=attempt,
                    status_code=response.status_code,
                    retryable=True,
                )
                self._log_failure("Market metadata provider request failed", provider_error)
                raise provider_error

            if response.is_error:
                provider_error = self._request_error(
                    "CoinGecko rejected the market metadata request.",
                    attempts=attempt,
                    status_code=response.status_code,
                    retryable=False,
                )
                self._log_failure("Market metadata provider request failed", provider_error)
                raise provider_error
            return response, attempt

        raise RuntimeError("Market metadata request loop exited unexpectedly.")

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float | None:
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                requested_delay = float(retry_after)
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(retry_after)
                    if retry_at.tzinfo is None:
                        retry_at = retry_at.replace(tzinfo=UTC)
                    requested_delay = (retry_at.astimezone(UTC) - datetime.now(UTC)).total_seconds()
                except (TypeError, ValueError, OverflowError):
                    requested_delay = self._backoff_delay(attempt)
            if not math.isfinite(requested_delay):
                requested_delay = self._backoff_delay(attempt)
            if requested_delay > self._max_retry_delay:
                return None
            return max(requested_delay, 0)
        return self._backoff_delay(attempt)

    def _backoff_delay(self, attempt: int) -> float:
        return min(
            self._retry_base_delay * (2 ** (attempt - 1)),
            self._max_retry_delay,
        )

    def _request_error(
        self,
        message: str,
        *,
        attempts: int,
        retryable: bool,
        status_code: int | None = None,
    ) -> MarketMetadataProviderError:
        return MarketMetadataProviderError(
            message,
            provider=self.provider_name,
            operation="fetch_markets",
            attempts=attempts,
            failed_at=datetime.now(UTC),
            status_code=status_code,
            retryable=retryable,
        )

    @staticmethod
    def _log_context(error: MarketMetadataProviderError) -> dict[str, object]:
        return {
            "provider": error.provider,
            "operation": error.operation,
            "attempts": error.attempts,
            "failed_at": error.failed_at.isoformat(),
            "status_code": error.status_code,
            "retryable": error.retryable,
        }

    @classmethod
    def _log_failure(
        cls,
        message: str,
        error: MarketMetadataProviderError,
        cause: BaseException | None = None,
    ) -> None:
        LOGGER.error(
            "%s: %s",
            message,
            error,
            extra=cls._log_context(error),
            exc_info=cause is not None,
        )

    def _normalize(
        self,
        record: CoinGeckoMarketRecord,
        *,
        retrieved_at: datetime,
    ) -> AssetMarketMetadata:
        provider_asset_id = record.id.strip()
        if not COIN_ID_PATTERN.fullmatch(provider_asset_id):
            raise ValueError("CoinGecko asset ID contains unsupported characters.")
        if record.last_updated.tzinfo is None or record.last_updated.utcoffset() is None:
            raise ValueError("CoinGecko source timestamp must include a timezone.")

        symbol = record.symbol.strip().upper()
        name = record.name.strip()
        if not symbol or not name:
            raise ValueError("CoinGecko assets must include a symbol and name.")

        return AssetMarketMetadata(
            provider=self.provider_name,
            provider_asset_id=provider_asset_id,
            canonical_asset_id=f"{self.provider_name}:{provider_asset_id}",
            symbol=symbol,
            name=name,
            current_price=record.current_price,
            market_cap=record.market_cap,
            market_cap_rank=record.market_cap_rank,
            total_volume=record.total_volume,
            source_timestamp=record.last_updated,
            retrieved_at=retrieved_at,
        )


def create_market_metadata_provider(
    settings: Settings,
    *,
    client: httpx.Client | None = None,
) -> MarketMetadataProvider:
    """Construct the configured market metadata provider."""
    if settings.market_metadata_provider != CoinGeckoMarketMetadataProvider.provider_name:
        raise ValueError(
            f"Unsupported market metadata provider: {settings.market_metadata_provider}"
        )
    api_key = settings.coingecko_api_key.get_secret_value() if settings.coingecko_api_key else None
    return CoinGeckoMarketMetadataProvider(api_key=api_key, client=client)
