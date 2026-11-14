from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from crypto_market_insights.indicators import calculate_indicators
from crypto_market_insights.market_data import VenueCandle

START = datetime(2026, 11, 10, tzinfo=UTC)
EVALUATION_TIME = datetime(2026, 11, 20, tzinfo=UTC)
TIMEFRAME_DURATION = {
    "1m": timedelta(minutes=1),
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
    "1w": timedelta(weeks=1),
    "15d": timedelta(days=15),
}


def make_candle(
    index: int,
    close: str = "100",
    *,
    interval: str = "1h",
    start: datetime = START,
    open_price: str | None = None,
    high: str | None = None,
    low: str | None = None,
    volume: str = "10",
    is_complete: bool = True,
) -> VenueCandle:
    close_value = Decimal(close)
    open_value = Decimal(open_price) if open_price is not None else close_value
    return VenueCandle(
        venue="kraken",
        venue_pair="XBT/USD",
        base_symbol="BTC",
        quote_symbol="USD",
        interval=interval,
        open_time=start + index * TIMEFRAME_DURATION[interval],
        close_time=start + (index + 1) * TIMEFRAME_DURATION[interval],
        open=open_value,
        high=Decimal(high) if high is not None else max(open_value, close_value) + 1,
        low=Decimal(low) if low is not None else min(open_value, close_value) - 1,
        close=close_value,
        volume=Decimal(volume),
        is_complete=is_complete,
        source_timestamp=start + (index + 1) * TIMEFRAME_DURATION[interval],
        retrieved_at=start + (index + 1) * TIMEFRAME_DURATION[interval] + timedelta(minutes=1),
    )


def calculate(candles: list[VenueCandle], *, volume_reliable: bool = False):
    return calculate_indicators(
        candles,
        now=EVALUATION_TIME,
        volume_reliable=volume_reliable,
    )


def test_flat_fixture_produces_known_indicator_values() -> None:
    result = calculate([make_candle(index) for index in range(200)], volume_reliable=True)

    assert result.ema_20.value == result.ema_50.value == result.ema_200.value == Decimal(100)
    assert result.rsi_14.value == Decimal(50)
    assert result.macd_line.value == result.macd_signal.value == result.macd_histogram.value == 0
    assert result.atr_14.value == Decimal(2)
    assert result.relative_volume_20.value == Decimal(1)
    assert result.realized_volatility_20.value == 0
    assert result.swing_support_20.status == "not_found"
    assert result.swing_resistance_20.status == "not_found"
    assert result.pivots.pivot.value == Decimal(100)
    assert result.pivots.resistance_1.value == Decimal(101)
    assert result.pivots.support_1.value == Decimal(99)
    assert result.vwap_session.value == Decimal(100)


def test_ema_uses_sma_seed_and_standard_smoothing() -> None:
    candles = [make_candle(index) for index in range(199)]
    candles.append(make_candle(199, "200"))

    result = calculate(candles)

    assert result.ema_20.value == Decimal(100) + Decimal(200) / Decimal(21)
    assert result.ema_50.value == Decimal(100) + Decimal(200) / Decimal(51)
    assert result.ema_200.value == Decimal("100.5")


@pytest.mark.parametrize(
    ("closes", "expected"),
    [
        ([str(100 + index) for index in range(16)], Decimal(100)),
        ([str(200 - index) for index in range(16)], Decimal(0)),
    ],
)
def test_rsi_14_uses_wilder_smoothing_for_directional_market(
    closes: list[str],
    expected: Decimal,
) -> None:
    result = calculate([make_candle(index, close) for index, close in enumerate(closes)])

    assert result.rsi_14.value == expected


def test_macd_uses_12_26_9_periods_and_reports_warmup_requirements() -> None:
    result = calculate([make_candle(index, "100") for index in range(33)])
    warming = calculate([make_candle(index, "100") for index in range(34)])

    assert result.macd_line.value == Decimal(0)
    assert result.macd_signal.status == "insufficient_data"
    assert result.macd_signal.required_candles == 34
    assert warming.macd_signal.value == Decimal(0)
    assert warming.macd_histogram.value == Decimal(0)


def test_atr_14_uses_true_range_and_wilder_average() -> None:
    candles = [
        make_candle(
            index,
            "100",
            high="115" if index == 13 else "101",
            low="85" if index == 13 else "99",
        )
        for index in range(14)
    ]

    result = calculate(candles)

    assert result.atr_14.value == Decimal(4)


def test_relative_volume_20_compares_current_volume_to_prior_bars() -> None:
    candles = [make_candle(index, volume=str(index + 1)) for index in range(21)]

    result = calculate(candles)

    assert result.relative_volume_20.value == Decimal(2)
    assert result.relative_volume_20.required_candles == 21


def test_relative_volume_reports_zero_baseline_volume() -> None:
    candles = [make_candle(index, volume="0") for index in range(21)]

    result = calculate(candles)

    assert result.relative_volume_20.value is None
    assert result.relative_volume_20.status == "zero_volume"


def test_realized_volatility_20_is_non_annualized_sum_of_squared_log_returns() -> None:
    closes = ["100", "110"] * 10 + ["100"]
    result = calculate([make_candle(index, close) for index, close in enumerate(closes)])
    expected = (Decimal(20) * Decimal("1.1").ln() ** 2).sqrt()

    assert result.realized_volatility_20.value is not None
    assert abs(result.realized_volatility_20.value - expected) < Decimal("1e-26")


def test_swing_levels_use_latest_confirmed_two_bar_pivots() -> None:
    lows = ["5", "4", "3", "4", "5", "4", "6"]
    highs = ["6", "7", "8", "7", "6", "9", "8"]
    candles = [
        make_candle(index, "6", high=high, low=low)
        for index, (high, low) in enumerate(zip(highs, lows, strict=True))
    ]

    result = calculate(candles)

    assert result.swing_support_20.value == Decimal(3)
    assert result.swing_resistance_20.value == Decimal(8)
    assert result.swing_support_20.reference_time == candles[2].open_time


def test_classic_pivots_use_latest_completed_candle() -> None:
    previous = make_candle(0, "100", high="110", low="90")
    latest = make_candle(1, "105", high="106", low="104")

    result = calculate([previous, latest])

    assert result.pivots.pivot.value == Decimal(105)
    assert result.pivots.resistance_1.value == Decimal(106)
    assert result.pivots.resistance_2.value == Decimal(107)
    assert result.pivots.resistance_3.value == Decimal(108)
    assert result.pivots.support_1.value == Decimal(104)
    assert result.pivots.support_2.value == Decimal(103)
    assert result.pivots.support_3.value == Decimal(102)
    assert result.pivots.pivot.reference_time == latest.open_time


def test_intraday_vwap_requires_verified_volume_and_complete_utc_session() -> None:
    candles = [
        make_candle(0, "101", open_price="99", high="103", low="97", volume="1"),
        make_candle(1, "104", open_price="101", high="106", low="100", volume="3"),
    ]

    unverified = calculate(candles)
    verified = calculate(candles, volume_reliable=True)

    assert unverified.vwap_session.status == "volume_unverified"
    assert verified.vwap_session.value == Decimal(1231) / Decimal(12)


def test_vwap_is_unsupported_for_daily_timeframe_and_missing_session_bars() -> None:
    daily = calculate([make_candle(0, interval="1d")], volume_reliable=True)
    late_start = START + timedelta(hours=1)
    incomplete = calculate(
        [
            make_candle(0, interval="1h", start=late_start),
            make_candle(1, interval="1h", start=late_start),
        ],
        volume_reliable=True,
    )

    assert daily.vwap_session.status == "unsupported_timeframe"
    assert incomplete.vwap_session.status == "incomplete_session"


def test_unfinished_and_future_candles_are_excluded_from_all_features() -> None:
    first = make_candle(0)
    unfinished = make_candle(1, is_complete=False)
    future = make_candle(2)
    now = first.close_time + timedelta(minutes=30)

    result = calculate_indicators([first, unfinished, future], now=now)

    assert result.closed_candle_count == 1
    assert result.excluded_unfinished_candle_count == 2
    assert result.as_of == first.close_time
    assert result.ema_20.status == "insufficient_data"
    assert result.pivots.pivot.value == first.close


def test_indicator_input_rejects_mixed_pairs_and_duplicate_times() -> None:
    candle = make_candle(0)
    other_pair = candle.model_copy(update={"venue_pair": "ETH/USD"})
    duplicate = make_candle(0)

    with pytest.raises(ValueError, match="same venue, pair, and timeframe"):
        calculate([candle, other_pair])
    with pytest.raises(ValueError, match="open times must be unique"):
        calculate([candle, duplicate])


def test_indicator_input_requires_timezone_aware_evaluation_time() -> None:
    with pytest.raises(ValueError, match="include a timezone"):
        calculate_indicators([make_candle(0)], now=datetime(2026, 11, 20))
