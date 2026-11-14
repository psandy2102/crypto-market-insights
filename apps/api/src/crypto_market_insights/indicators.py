"""Deterministic technical indicators over completed, venue-specific candles."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Literal

from crypto_market_insights.kraken import INTERVAL_MINUTES
from crypto_market_insights.market_data import VenueCandle

IndicatorStatus = Literal[
    "available",
    "insufficient_data",
    "not_found",
    "unsupported_timeframe",
    "volume_unverified",
    "incomplete_session",
    "zero_volume",
]
INTRADAY_INTERVALS = frozenset({"1m", "5m", "15m", "30m", "1h", "4h"})
SWING_LOOKBACK = 20
SWING_RADIUS = 2
RELATIVE_VOLUME_PERIOD = 20
REALIZED_VOLATILITY_PERIOD = 20


@dataclass(frozen=True)
class IndicatorValue:
    """A value with its input-availability status and source candle."""

    value: Decimal | None
    status: IndicatorStatus
    required_candles: int
    available_candles: int
    reference_time: datetime | None = None


@dataclass(frozen=True)
class ClassicPivotLevels:
    """Classic support/resistance levels derived from the latest closed candle."""

    pivot: IndicatorValue
    resistance_1: IndicatorValue
    resistance_2: IndicatorValue
    resistance_3: IndicatorValue
    support_1: IndicatorValue
    support_2: IndicatorValue
    support_3: IndicatorValue


@dataclass(frozen=True)
class IndicatorSnapshot:
    """Latest indicator values plus the exact completed-candle input boundary."""

    venue: str
    venue_pair: str
    timeframe: str
    evaluation_time: datetime
    as_of: datetime | None
    closed_candle_count: int
    excluded_unfinished_candle_count: int
    ema_20: IndicatorValue
    ema_50: IndicatorValue
    ema_200: IndicatorValue
    rsi_14: IndicatorValue
    macd_line: IndicatorValue
    macd_signal: IndicatorValue
    macd_histogram: IndicatorValue
    atr_14: IndicatorValue
    relative_volume_20: IndicatorValue
    realized_volatility_20: IndicatorValue
    swing_support_20: IndicatorValue
    swing_resistance_20: IndicatorValue
    pivots: ClassicPivotLevels
    vwap_session: IndicatorValue


def calculate_indicators(
    candles: Sequence[VenueCandle],
    *,
    now: datetime | None = None,
    volume_reliable: bool = False,
) -> IndicatorSnapshot:
    """Calculate latest values from closed candles only.

    ``close_time`` is the exclusive end of a candle. A candle is eligible only
    when its provider completion flag is true and its close time is no later
    than ``now``. VWAP additionally requires an explicit volume reliability
    assertion and a gap-free UTC intraday session from midnight.
    """
    if not candles:
        raise ValueError("At least one candle is required to identify the market and timeframe.")

    evaluation_time = now or datetime.now(UTC)
    if evaluation_time.tzinfo is None or evaluation_time.utcoffset() is None:
        raise ValueError("now must include a timezone.")
    evaluation_time = evaluation_time.astimezone(UTC)

    first = candles[0]
    timeframe_minutes = INTERVAL_MINUTES.get(first.interval)
    if timeframe_minutes is None:
        raise ValueError(f"Unsupported timeframe: {first.interval}")
    expected_duration = timedelta(minutes=timeframe_minutes)

    for candle in candles:
        if (
            candle.venue != first.venue
            or candle.venue_pair != first.venue_pair
            or candle.base_symbol != first.base_symbol
            or candle.quote_symbol != first.quote_symbol
            or candle.interval != first.interval
        ):
            raise ValueError("All candles must belong to the same venue, pair, and timeframe.")
        if candle.close_time - candle.open_time != expected_duration:
            raise ValueError("Candle duration does not match its declared timeframe.")

    ordered = sorted(candles, key=lambda candle: candle.open_time)
    if any(
        left.open_time == right.open_time for left, right in zip(ordered, ordered[1:], strict=False)
    ):
        raise ValueError("Candle open times must be unique.")

    closed = [
        candle for candle in ordered if candle.is_complete and candle.close_time <= evaluation_time
    ]
    excluded_count = len(ordered) - len(closed)
    count = len(closed)
    as_of = closed[-1].close_time if closed else None
    closes = [candle.close for candle in closed]

    ema_values = {
        period: _ema_series(closes, period)[-1] if count >= period else None
        for period in (20, 50, 200)
    }
    rsi = _rsi(closed, 14)
    macd_line, macd_signal = _macd(closes)
    atr = _atr(closed, 14)
    relative_volume = _relative_volume(closed, RELATIVE_VOLUME_PERIOD)
    realized_volatility = _realized_volatility(closed, REALIZED_VOLATILITY_PERIOD)
    swing_support, swing_resistance = _swing_levels(closed)
    pivots = _pivot_levels(closed)
    vwap = _session_vwap(
        closed,
        timeframe=first.interval,
        volume_reliable=volume_reliable,
    )

    return IndicatorSnapshot(
        venue=first.venue,
        venue_pair=first.venue_pair,
        timeframe=first.interval,
        evaluation_time=evaluation_time,
        as_of=as_of,
        closed_candle_count=count,
        excluded_unfinished_candle_count=excluded_count,
        ema_20=_indicator_value(ema_values[20], 20, count),
        ema_50=_indicator_value(ema_values[50], 50, count),
        ema_200=_indicator_value(ema_values[200], 200, count),
        rsi_14=_indicator_value(rsi, 15, count),
        macd_line=_indicator_value(macd_line, 26, count),
        macd_signal=_indicator_value(macd_signal, 34, count),
        macd_histogram=_indicator_value(
            macd_line - macd_signal if macd_line is not None and macd_signal is not None else None,
            34,
            count,
        ),
        atr_14=_indicator_value(atr, 14, count),
        relative_volume_20=relative_volume,
        realized_volatility_20=_indicator_value(realized_volatility, 21, count),
        swing_support_20=swing_support,
        swing_resistance_20=swing_resistance,
        pivots=pivots,
        vwap_session=vwap,
    )


def _indicator_value(
    value: Decimal | None,
    required_candles: int,
    available_candles: int,
    *,
    status: IndicatorStatus | None = None,
    reference_time: datetime | None = None,
) -> IndicatorValue:
    resolved_status = status or ("available" if value is not None else "insufficient_data")
    return IndicatorValue(
        value=value,
        status=resolved_status,
        required_candles=required_candles,
        available_candles=available_candles,
        reference_time=reference_time,
    )


def _ema_series(values: Sequence[Decimal], period: int) -> list[Decimal | None]:
    result: list[Decimal | None] = [None] * len(values)
    if len(values) < period:
        return result
    seed = sum(values[:period], Decimal(0)) / Decimal(period)
    result[period - 1] = seed
    multiplier = Decimal(2) / Decimal(period + 1)
    for index in range(period, len(values)):
        previous = result[index - 1]
        assert previous is not None
        result[index] = (values[index] - previous) * multiplier + previous
    return result


def _rsi(candles: Sequence[VenueCandle], period: int) -> Decimal | None:
    if len(candles) < period + 1:
        return None
    changes = [
        current.close - previous.close
        for previous, current in zip(candles, candles[1:], strict=False)
    ]
    gains = [max(change, Decimal(0)) for change in changes]
    losses = [max(-change, Decimal(0)) for change in changes]
    average_gain = sum(gains[:period], Decimal(0)) / Decimal(period)
    average_loss = sum(losses[:period], Decimal(0)) / Decimal(period)
    for gain, loss in zip(gains[period:], losses[period:], strict=False):
        average_gain = (average_gain * Decimal(period - 1) + gain) / Decimal(period)
        average_loss = (average_loss * Decimal(period - 1) + loss) / Decimal(period)
    if average_gain == 0 and average_loss == 0:
        return Decimal(50)
    if average_loss == 0:
        return Decimal(100)
    if average_gain == 0:
        return Decimal(0)
    relative_strength = average_gain / average_loss
    return Decimal(100) - Decimal(100) / (Decimal(1) + relative_strength)


def _macd(closes: Sequence[Decimal]) -> tuple[Decimal | None, Decimal | None]:
    fast = _ema_series(closes, 12)
    slow = _ema_series(closes, 26)
    macd_values = [
        fast_value - slow_value
        for fast_value, slow_value in zip(fast, slow, strict=True)
        if fast_value is not None and slow_value is not None
    ]
    if not macd_values:
        return None, None
    signal_values = _ema_series(macd_values, 9)
    return macd_values[-1], signal_values[-1]


def _atr(candles: Sequence[VenueCandle], period: int) -> Decimal | None:
    if len(candles) < period:
        return None
    true_ranges = [candles[0].high - candles[0].low]
    for previous, current in zip(candles, candles[1:], strict=False):
        true_ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    average = sum(true_ranges[:period], Decimal(0)) / Decimal(period)
    for true_range in true_ranges[period:]:
        average = (average * Decimal(period - 1) + true_range) / Decimal(period)
    return average


def _relative_volume(candles: Sequence[VenueCandle], period: int) -> IndicatorValue:
    if len(candles) < period + 1:
        return _indicator_value(None, period + 1, len(candles))
    previous_volumes = [candle.volume for candle in candles[-period - 1 : -1]]
    average_volume = sum(previous_volumes, Decimal(0)) / Decimal(period)
    if average_volume == 0:
        return _indicator_value(
            None,
            period + 1,
            len(candles),
            status="zero_volume",
        )
    return _indicator_value(
        candles[-1].volume / average_volume,
        period + 1,
        len(candles),
    )


def _realized_volatility(candles: Sequence[VenueCandle], period: int) -> Decimal | None:
    if len(candles) < period + 1:
        return None
    returns = [
        (current.close / previous.close).ln()
        for previous, current in zip(candles[-period - 1 :], candles[-period:], strict=False)
    ]
    return sum((value * value for value in returns), Decimal(0)).sqrt()


def _swing_levels(
    candles: Sequence[VenueCandle],
) -> tuple[IndicatorValue, IndicatorValue]:
    count = len(candles)
    required = SWING_RADIUS * 2 + 1
    if count < required:
        unavailable = _indicator_value(None, required, count)
        return unavailable, unavailable

    start = max(0, count - SWING_LOOKBACK)
    support: VenueCandle | None = None
    resistance: VenueCandle | None = None
    for index in range(start + SWING_RADIUS, count - SWING_RADIUS):
        before = candles[index - SWING_RADIUS : index]
        after = candles[index + 1 : index + SWING_RADIUS + 1]
        neighbors = [*before, *after]
        candidate = candles[index]
        if all(candidate.low < neighbor.low for neighbor in neighbors):
            support = candidate
        if all(candidate.high > neighbor.high for neighbor in neighbors):
            resistance = candidate

    support_value = _indicator_value(
        support.low if support else None,
        required,
        count,
        status="available" if support else "not_found",
        reference_time=support.open_time if support else None,
    )
    resistance_value = _indicator_value(
        resistance.high if resistance else None,
        required,
        count,
        status="available" if resistance else "not_found",
        reference_time=resistance.open_time if resistance else None,
    )
    return support_value, resistance_value


def _pivot_levels(candles: Sequence[VenueCandle]) -> ClassicPivotLevels:
    previous = candles[-1] if candles else None
    values: dict[str, Decimal | None]
    if previous is None:
        values = {name: None for name in ("pivot", "r1", "r2", "r3", "s1", "s2", "s3")}
    else:
        high, low, close = previous.high, previous.low, previous.close
        pivot = (high + low + close) / Decimal(3)
        values = {
            "pivot": pivot,
            "r1": Decimal(2) * pivot - low,
            "r2": pivot + high - low,
            "r3": high + Decimal(2) * (pivot - low),
            "s1": Decimal(2) * pivot - high,
            "s2": pivot - high + low,
            "s3": low - Decimal(2) * (high - pivot),
        }
    reference_time = previous.open_time if previous else None

    def value(name: str) -> IndicatorValue:
        return _indicator_value(
            values[name],
            1,
            len(candles),
            reference_time=reference_time,
        )

    return ClassicPivotLevels(
        pivot=value("pivot"),
        resistance_1=value("r1"),
        resistance_2=value("r2"),
        resistance_3=value("r3"),
        support_1=value("s1"),
        support_2=value("s2"),
        support_3=value("s3"),
    )


def _session_vwap(
    candles: Sequence[VenueCandle],
    *,
    timeframe: str,
    volume_reliable: bool,
) -> IndicatorValue:
    if timeframe not in INTRADAY_INTERVALS:
        return _indicator_value(
            None,
            1,
            len(candles),
            status="unsupported_timeframe",
        )
    if not volume_reliable:
        return _indicator_value(
            None,
            1,
            len(candles),
            status="volume_unverified",
        )
    if not candles:
        return _indicator_value(None, 1, 0)

    latest = candles[-1]
    session_start = datetime.combine(latest.open_time.date(), time.min, tzinfo=UTC)
    session = [candle for candle in candles if candle.open_time.date() == latest.open_time.date()]
    duration = timedelta(minutes=INTERVAL_MINUTES[timeframe])
    expected_count = int((latest.open_time - session_start) / duration) + 1
    contiguous = (
        session[0].open_time == session_start
        and len(session) == expected_count
        and all(
            current.open_time - previous.open_time == duration
            for previous, current in zip(session, session[1:], strict=False)
        )
    )
    if not contiguous:
        return _indicator_value(
            None,
            expected_count,
            len(session),
            status="incomplete_session",
        )

    total_volume = sum((candle.volume for candle in session), Decimal(0))
    if total_volume == 0:
        return _indicator_value(
            None,
            expected_count,
            len(session),
            status="zero_volume",
        )
    weighted_price = sum(
        (
            (candle.high + candle.low + candle.close) / Decimal(3) * candle.volume
            for candle in session
        ),
        Decimal(0),
    )
    return _indicator_value(
        weighted_price / total_volume,
        expected_count,
        len(session),
        reference_time=latest.close_time,
    )
