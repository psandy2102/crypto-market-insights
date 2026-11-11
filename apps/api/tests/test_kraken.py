from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from crypto_market_insights.config import Settings
from crypto_market_insights.kraken import (
    KrakenMarketDataProvider,
    VenueMarketDataError,
    create_venue_market_data_provider,
)
from crypto_market_insights.market_data import VenueCandle, VenueMarketDataProvider

PAIR_RESPONSE = {
    "error": [],
    "result": {
        "XXBTZUSD": {
            "altname": "XBTUSD",
            "wsname": "XBT/USD",
            "base": "XXBT",
            "quote": "ZUSD",
            "status": "online",
        }
    },
}

OHLC_RESPONSE = {
    "error": [],
    "result": {
        "XXBTZUSD": [
            [1794403200, "100.1", "110.5", "99.5", "105.25", "104.2", "12.34567890", 42],
            [1794406800, "105.25", "111", "104", "109.75", "108", "10.5", 36],
        ],
        "last": 1794406800,
    },
}

TICKER_RESPONSE = {
    "error": [],
    "result": {
        "XXBTZUSD": {
            "a": ["110.25", "1", "1.0"],
            "b": ["110.00", "1", "1.0"],
            "c": ["110.10", "0.01"],
            "v": ["100.5", "250.75"],
        }
    },
}


def create_client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler)


def test_kraken_fetches_and_normalizes_sample_candles() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/AssetPairs"):
            return httpx.Response(200, json=PAIR_RESPONSE, request=request)
        if request.url.path.endswith("/OHLC"):
            return httpx.Response(200, json=OHLC_RESPONSE, request=request)
        pytest.fail(f"Unexpected Kraken request: {request.url}")

    since = datetime(2026, 11, 10, 0, 0, tzinfo=UTC)
    with create_client(httpx.MockTransport(handle)) as client:
        provider = KrakenMarketDataProvider(client=client, sleep=lambda _: None)
        provider_contract: VenueMarketDataProvider = provider
        candles = provider_contract.fetch_candles(
            base_symbol="btc",
            quote_symbol="usd",
            interval="1h",
            since=since,
        )

    assert len(candles) == 2
    first, current = candles
    assert isinstance(first, VenueCandle)
    assert first.venue == "kraken"
    assert first.venue_pair == "XBT/USD"
    assert first.base_symbol == "BTC"
    assert first.quote_symbol == "USD"
    assert first.interval == "1h"
    assert first.open_time == datetime.fromtimestamp(1794403200, tz=UTC)
    assert first.close_time == first.open_time + timedelta(hours=1)
    assert first.open == Decimal("100.1")
    assert first.high == Decimal("110.5")
    assert first.low == Decimal("99.5")
    assert first.close == Decimal("105.25")
    assert first.volume == Decimal("12.34567890")
    assert first.is_complete is True
    assert first.source_timestamp == first.close_time
    assert first.retrieved_at.tzinfo == UTC
    assert current.is_complete is False
    assert requests[0].url.path.endswith("/AssetPairs")
    assert requests[1].url.path.endswith("/OHLC")
    assert requests[1].url.params["pair"] == "XBTUSD"
    assert requests[1].url.params["interval"] == "60"
    assert requests[1].url.params["since"] == str(int(since.timestamp()))


def test_kraken_fetches_ticker_snapshot_from_same_venue() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/AssetPairs"):
            return httpx.Response(200, json=PAIR_RESPONSE, request=request)
        if request.url.path.endswith("/Ticker"):
            return httpx.Response(200, json=TICKER_RESPONSE, request=request)
        pytest.fail(f"Unexpected Kraken request: {request.url}")

    with create_client(httpx.MockTransport(handle)) as client:
        provider = KrakenMarketDataProvider(client=client)
        snapshot = provider.fetch_market_snapshot(base_symbol="BTC", quote_symbol="USD")

    assert snapshot.venue == "kraken"
    assert snapshot.venue_pair == "XBT/USD"
    assert snapshot.last_price == Decimal("110.10")
    assert snapshot.best_bid == Decimal("110.00")
    assert snapshot.best_ask == Decimal("110.25")
    assert snapshot.volume_today == Decimal("100.5")
    assert snapshot.volume_24h == Decimal("250.75")
    assert snapshot.source_timestamp == snapshot.retrieved_at
    assert requests[-1].url.path.endswith("/Ticker")
    assert requests[-1].url.params["pair"] == "XBTUSD"


@pytest.mark.parametrize(
    ("pairs", "message"),
    [
        ({}, "unavailable"),
        (
            {
                **PAIR_RESPONSE["result"],
                "XXBTZUSD_ALT": {
                    **PAIR_RESPONSE["result"]["XXBTZUSD"],
                    "altname": "XXBTZUSD",
                },
            },
            "ambiguous",
        ),
        (
            {
                "XXBTZUSD": {
                    **PAIR_RESPONSE["result"]["XXBTZUSD"],
                    "status": "cancel_only",
                }
            },
            "not online",
        ),
    ],
)
def test_pair_resolution_fails_for_unavailable_ambiguous_or_inactive_pairs(
    pairs: dict[str, object],
    message: str,
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"error": [], "result": pairs},
            request=request,
        )

    with create_client(httpx.MockTransport(handle)) as client:
        provider = KrakenMarketDataProvider(client=client)
        with pytest.raises(VenueMarketDataError, match=message):
            provider.fetch_candles(
                base_symbol="BTC",
                quote_symbol="USD",
                interval="1h",
            )


def test_kraken_exchange_and_malformed_ohlc_errors_are_visible() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/AssetPairs"):
            return httpx.Response(200, json=PAIR_RESPONSE, request=request)
        return httpx.Response(
            200,
            json={"error": ["EQuery:Unknown asset pair"], "result": {}},
            request=request,
        )

    with create_client(httpx.MockTransport(handle)) as client:
        provider = KrakenMarketDataProvider(client=client)
        with pytest.raises(VenueMarketDataError, match="Unknown asset pair"):
            provider.fetch_candles(
                base_symbol="BTC",
                quote_symbol="USD",
                interval="1h",
            )

    def malformed_handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/AssetPairs"):
            return httpx.Response(200, json=PAIR_RESPONSE, request=request)
        bad_response = {
            "error": [],
            "result": {"XXBTZUSD": [[1794403200, "100", "90", "99", "105", "104", "12", 42]]},
        }
        return httpx.Response(200, json=bad_response, request=request)

    with create_client(httpx.MockTransport(malformed_handle)) as client:
        provider = KrakenMarketDataProvider(client=client)
        with pytest.raises(VenueMarketDataError, match="invalid normalized candle"):
            provider.fetch_candles(
                base_symbol="BTC",
                quote_symbol="USD",
                interval="1h",
            )


def test_kraken_retries_rate_limited_requests_with_retry_after() -> None:
    requests: list[httpx.Request] = []
    delays: list[float] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/AssetPairs"):
            if len(requests) == 1:
                return httpx.Response(429, headers={"Retry-After": "0"}, request=request)
            return httpx.Response(200, json=PAIR_RESPONSE, request=request)
        return httpx.Response(200, json=OHLC_RESPONSE, request=request)

    with create_client(httpx.MockTransport(handle)) as client:
        provider = KrakenMarketDataProvider(client=client, sleep=delays.append)
        candles = provider.fetch_candles(
            base_symbol="BTC",
            quote_symbol="USD",
            interval="1h",
        )

    assert len(candles) == 2
    assert len(requests) == 3
    assert delays == [0]


def test_bad_intervals_naive_since_and_unknown_venue_fail_before_requests() -> None:
    def unexpected_request(request: httpx.Request) -> httpx.Response:
        pytest.fail(f"Unexpected Kraken request: {request.url}")

    with create_client(httpx.MockTransport(unexpected_request)) as client:
        provider = KrakenMarketDataProvider(client=client)
        with pytest.raises(ValueError, match="Unsupported Kraken candle interval"):
            provider.fetch_candles(
                base_symbol="BTC",
                quote_symbol="USD",
                interval="2h",
            )
        with pytest.raises(ValueError, match="since must include a timezone"):
            provider.fetch_candles(
                base_symbol="BTC",
                quote_symbol="USD",
                interval="1h",
                since=datetime(2026, 11, 10),
            )

    with pytest.raises(ValueError, match="Unsupported market-data venue"):
        create_venue_market_data_provider(Settings(market_data_venue="unknown"))


def test_venue_factory_constructs_kraken_provider() -> None:
    provider = create_venue_market_data_provider(Settings(market_data_venue="kraken"))
    assert isinstance(provider, KrakenMarketDataProvider)
    provider.close()
