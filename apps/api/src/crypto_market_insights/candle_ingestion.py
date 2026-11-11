"""Candle-batch validation and ingestion orchestration."""

import logging
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from crypto_market_insights.kraken import INTERVAL_MINUTES
from crypto_market_insights.market_data import VenueCandle, VenueMarketDataProvider

LOGGER = logging.getLogger(__name__)
SYMBOL_ALIASES = {"XBT": "BTC", "XXBT": "BTC", "XETH": "ETH"}


class CandleDiagnostic(BaseModel):
    """Actionable validation or data-quality diagnostic."""

    model_config = ConfigDict(frozen=True)

    code: str
    severity: str
    message: str
    open_time: datetime | None = None


class CandleIngestionError(ValueError):
    """A rejected candle batch and its machine-readable diagnostics."""

    def __init__(self, diagnostics: list[CandleDiagnostic]) -> None:
        self.diagnostics = diagnostics
        summary = "; ".join(diagnostic.message for diagnostic in diagnostics)
        super().__init__(summary)


class CandleRepositoryProtocol(Protocol):
    """Persistence operations required by the ingestion service."""

    def start_run(self, *, venue: str, venue_pair: str, interval: str) -> uuid.UUID: ...

    def complete_run(
        self,
        *,
        run_id: uuid.UUID,
        venue: str,
        candles_to_store: list[VenueCandle],
        diagnostics: list[dict[str, Any]],
        received_count: int,
    ) -> int: ...

    def fail_run(
        self,
        *,
        run_id: uuid.UUID,
        venue: str,
        error: Exception,
        diagnostics: list[dict[str, Any]],
        received_count: int = 0,
    ) -> None: ...


class CandleBatchValidator:
    """Validate identities, duplicates, gaps, freshness, and price outliers."""

    def __init__(
        self,
        *,
        max_staleness_intervals: int = 3,
        max_price_change_fraction: Decimal = Decimal("0.50"),
        max_range_fraction: Decimal = Decimal("0.75"),
    ) -> None:
        if max_staleness_intervals < 1:
            raise ValueError("max_staleness_intervals must be at least 1.")
        if max_price_change_fraction <= 0 or max_range_fraction <= 0:
            raise ValueError("Outlier thresholds must be positive.")
        self._max_staleness_intervals = max_staleness_intervals
        self._max_price_change_fraction = max_price_change_fraction
        self._max_range_fraction = max_range_fraction

    def validate(
        self,
        candles: Sequence[VenueCandle],
        *,
        venue: str,
        base_symbol: str,
        quote_symbol: str,
        interval: str,
        now: datetime,
    ) -> tuple[list[VenueCandle], list[CandleDiagnostic]]:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must include a timezone.")
        if interval not in INTERVAL_MINUTES:
            raise ValueError(f"Unsupported candle interval: {interval}")
        if not candles:
            raise CandleIngestionError(
                [
                    CandleDiagnostic(
                        code="empty_batch",
                        severity="error",
                        message="The venue returned no candles.",
                    )
                ]
            )

        interval_length = timedelta(minutes=INTERVAL_MINUTES[interval])
        diagnostics: list[CandleDiagnostic] = []
        expected_base = self._normalize_symbol(base_symbol)
        expected_quote = self._normalize_symbol(quote_symbol)
        unique: dict[tuple[str, str, str, datetime], VenueCandle] = {}

        for candle in candles:
            if (
                candle.venue != venue
                or candle.interval != interval
                or self._normalize_symbol(candle.base_symbol) != expected_base
                or self._normalize_symbol(candle.quote_symbol) != expected_quote
            ):
                diagnostics.append(
                    CandleDiagnostic(
                        code="identity_mismatch",
                        severity="error",
                        message=(
                            "Candle venue, pair symbols, or interval do not match the "
                            "requested ingestion."
                        ),
                        open_time=candle.open_time,
                    )
                )
                continue
            key = (candle.venue, candle.venue_pair, candle.interval, candle.open_time)
            existing = unique.get(key)
            if existing is None:
                unique[key] = candle
            elif self._values_match(existing, candle):
                diagnostics.append(
                    CandleDiagnostic(
                        code="duplicate_candle",
                        severity="warning",
                        message="Duplicate candle in the provider response was collapsed.",
                        open_time=candle.open_time,
                    )
                )
            else:
                diagnostics.append(
                    CandleDiagnostic(
                        code="conflicting_duplicate",
                        severity="error",
                        message="Duplicate candle key has conflicting OHLCV values.",
                        open_time=candle.open_time,
                    )
                )

        if any(diagnostic.severity == "error" for diagnostic in diagnostics):
            raise CandleIngestionError(diagnostics)

        ordered = sorted(unique.values(), key=lambda candle: candle.open_time)
        completed = [candle for candle in ordered if candle.is_complete]
        if not completed:
            raise CandleIngestionError(
                [
                    CandleDiagnostic(
                        code="no_completed_candles",
                        severity="error",
                        message="The provider response contains no completed candles.",
                    )
                ]
            )

        for previous, current in zip(ordered, ordered[1:], strict=False):
            time_delta = current.open_time - previous.open_time
            if time_delta > interval_length:
                missing_count = max(int(time_delta / interval_length) - 1, 1)
                diagnostics.append(
                    CandleDiagnostic(
                        code="candle_gap",
                        severity="warning",
                        message=(
                            f"Provider response has a gap of {missing_count} candle interval(s)."
                        ),
                        open_time=current.open_time,
                    )
                )

        latest_complete = completed[-1]
        age = now.astimezone(UTC) - latest_complete.close_time
        allowed_staleness = interval_length * self._max_staleness_intervals
        if age > allowed_staleness:
            raise CandleIngestionError(
                diagnostics
                + [
                    CandleDiagnostic(
                        code="stale_candles",
                        severity="error",
                        message=(
                            f"Latest completed candle is {age} old; the configured "
                            f"maximum is {allowed_staleness}."
                        ),
                        open_time=latest_complete.open_time,
                    )
                ]
            )
        if age < -interval_length:
            raise CandleIngestionError(
                diagnostics
                + [
                    CandleDiagnostic(
                        code="future_candle",
                        severity="error",
                        message=(
                            "Latest completed candle closes more than one interval in the future."
                        ),
                        open_time=latest_complete.open_time,
                    )
                ]
            )

        for previous, current in zip(completed, completed[1:], strict=False):
            close_change = abs(current.close - previous.close) / previous.close
            range_fraction = (current.high - current.low) / previous.close
            if close_change > self._max_price_change_fraction:
                diagnostics.append(
                    CandleDiagnostic(
                        code="price_change_outlier",
                        severity="error",
                        message=(
                            f"Close changed by {close_change:.2%}, above the "
                            f"{self._max_price_change_fraction:.2%} threshold."
                        ),
                        open_time=current.open_time,
                    )
                )
            if range_fraction > self._max_range_fraction:
                diagnostics.append(
                    CandleDiagnostic(
                        code="price_range_outlier",
                        severity="error",
                        message=(
                            f"Candle range was {range_fraction:.2%} of the prior close, "
                            f"above the {self._max_range_fraction:.2%} threshold."
                        ),
                        open_time=current.open_time,
                    )
                )

        if any(diagnostic.severity == "error" for diagnostic in diagnostics):
            raise CandleIngestionError(diagnostics)
        return ordered, diagnostics

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        normalized = symbol.strip().upper()
        return SYMBOL_ALIASES.get(normalized, normalized)

    @staticmethod
    def _values_match(left: VenueCandle, right: VenueCandle) -> bool:
        return all(
            getattr(left, field) == getattr(right, field)
            for field in (
                "open",
                "high",
                "low",
                "close",
                "volume",
                "is_complete",
                "source_timestamp",
            )
        )


class CandleIngestionService:
    """Run, validate, and persist a venue candle fetch as one tracked operation."""

    def __init__(
        self,
        repository: CandleRepositoryProtocol,
        *,
        validator: CandleBatchValidator | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._validator = validator or CandleBatchValidator()
        self._clock = clock

    def ingest(
        self,
        provider: VenueMarketDataProvider,
        *,
        base_symbol: str,
        quote_symbol: str,
        interval: str,
        since: datetime | None = None,
    ) -> dict[str, Any]:
        if interval not in INTERVAL_MINUTES:
            raise ValueError(f"Unsupported candle interval: {interval}")
        venue = provider.venue_name
        requested_pair = f"{base_symbol.strip().upper()}/{quote_symbol.strip().upper()}"
        run_id = self._repository.start_run(
            venue=venue,
            venue_pair=requested_pair,
            interval=interval,
        )
        received_count = 0
        try:
            fetched = provider.fetch_candles(
                base_symbol=base_symbol,
                quote_symbol=quote_symbol,
                interval=interval,
                since=since,
            )
            received_count = len(fetched)
            validated, diagnostics = self._validator.validate(
                fetched,
                venue=venue,
                base_symbol=base_symbol,
                quote_symbol=quote_symbol,
                interval=interval,
                now=self._clock(),
            )
            stored_count = self._repository.complete_run(
                run_id=run_id,
                venue=venue,
                candles_to_store=validated,
                diagnostics=[diagnostic.model_dump(mode="json") for diagnostic in diagnostics],
                received_count=received_count,
            )
        except Exception as error:
            failure_diagnostics = (
                [diagnostic.model_dump(mode="json") for diagnostic in error.diagnostics]
                if isinstance(error, CandleIngestionError)
                else [
                    {
                        "code": "ingestion_failed",
                        "severity": "error",
                        "message": str(error),
                    }
                ]
            )
            self._repository.fail_run(
                run_id=run_id,
                venue=venue,
                error=error,
                diagnostics=failure_diagnostics,
                received_count=received_count,
            )
            LOGGER.error(
                "Candle ingestion failed",
                extra={
                    "venue": venue,
                    "pair": requested_pair,
                    "interval": interval,
                    "run_id": str(run_id),
                    "received_count": received_count,
                    "diagnostics": failure_diagnostics,
                },
                exc_info=True,
            )
            raise

        return {
            "run_id": run_id,
            "venue": venue,
            "pair": validated[0].venue_pair,
            "interval": interval,
            "status": "succeeded",
            "received_count": received_count,
            "upserted_count": stored_count,
            "diagnostics": diagnostics,
        }
