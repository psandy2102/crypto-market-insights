from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from crypto_market_insights.coingecko import (
    CoinGeckoMarketMetadataProvider,
    CoinGeckoResponseError,
    MarketMetadataProviderError,
    create_market_metadata_provider,
)
from crypto_market_insights.config import Settings
from crypto_market_insights.market_metadata import MarketMetadataProvider

MARKET_RECORD = {
    "id": "bitcoin",
    "symbol": "btc",
    "name": "Bitcoin",
    "current_price": 123.45,
    "market_cap": 2_400_000_000_000.12,
    "market_cap_rank": 1,
    "total_volume": 34_000_000_000.5,
    "last_updated": "2026-11-10T12:34:56.000Z",
}


def make_client(handler: httpx.MockTransport | httpx.BaseTransport) -> httpx.Client:
    return httpx.Client(transport=handler)


def test_coingecko_response_normalizes_market_data_and_provenance() -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[MARKET_RECORD], request=request)

    with make_client(httpx.MockTransport(handle)) as client:
        provider = CoinGeckoMarketMetadataProvider(
            "demo-secret",
            client=client,
            sleep=lambda _: None,
        )
        result = provider.fetch_markets(quote_currency=" USD ", page=2, per_page=20)

    assert len(result) == 1
    asset = result[0]
    provider_contract: MarketMetadataProvider = provider
    assert provider_contract.provider_name == "coingecko"
    assert asset.provider == "coingecko"
    assert asset.provider_asset_id == "bitcoin"
    assert asset.canonical_asset_id == "coingecko:bitcoin"
    assert asset.symbol == "BTC"
    assert asset.name == "Bitcoin"
    assert asset.current_price == Decimal("123.45")
    assert asset.market_cap == Decimal("2400000000000.12")
    assert asset.market_cap_rank == 1
    assert asset.total_volume == Decimal("34000000000.5")
    assert asset.source_timestamp == datetime(2026, 11, 10, 12, 34, 56, tzinfo=UTC)
    assert asset.retrieved_at.tzinfo == UTC
    assert requests[0].url.params["vs_currency"] == "usd"
    assert requests[0].url.params["page"] == "2"
    assert requests[0].url.params["per_page"] == "20"
    assert requests[0].url.params["order"] == "market_cap_desc"
    assert requests[0].headers["x-cg-demo-api-key"] == "demo-secret"


def test_rate_limited_request_retries_using_retry_after() -> None:
    requests: list[httpx.Request] = []
    delays: list[float] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"}, request=request)
        return httpx.Response(200, json=[MARKET_RECORD], request=request)

    with make_client(httpx.MockTransport(handle)) as client:
        provider = CoinGeckoMarketMetadataProvider(
            client=client,
            sleep=delays.append,
        )
        result = provider.fetch_markets(quote_currency="usd")

    assert len(result) == 1
    assert len(requests) == 2
    assert delays == [0]


def test_rate_limit_with_long_retry_after_fails_without_retrying_early() -> None:
    requests: list[httpx.Request] = []
    delays: list[float] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(429, headers={"Retry-After": "600"}, request=request)

    with make_client(httpx.MockTransport(handle)) as client:
        provider = CoinGeckoMarketMetadataProvider(
            client=client,
            sleep=delays.append,
            max_attempts=3,
            max_retry_delay=30,
        )
        with pytest.raises(MarketMetadataProviderError) as error:
            provider.fetch_markets(quote_currency="usd")

    assert len(requests) == 1
    assert delays == []
    assert error.value.status_code == 429
    assert error.value.attempts == 1


def test_server_error_exhausts_retries_and_logs_failure(caplog: pytest.LogCaptureFixture) -> None:
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(503, request=request)

    with make_client(httpx.MockTransport(handle)) as client:
        provider = CoinGeckoMarketMetadataProvider(
            client=client,
            sleep=lambda _: None,
            max_attempts=3,
        )
        with pytest.raises(MarketMetadataProviderError) as error:
            provider.fetch_markets(quote_currency="usd")

    assert len(requests) == 3
    assert error.value.provider == "coingecko"
    assert error.value.attempts == 3
    assert error.value.status_code == 503
    assert error.value.retryable is True
    assert error.value.failed_at.tzinfo == UTC
    failure = next(
        record
        for record in caplog.records
        if record.message.startswith("Market metadata provider request failed")
    )
    assert failure.provider == "coingecko"
    assert failure.status_code == 503
    assert failure.attempts == 3


def test_transient_timeout_retries() -> None:
    attempts = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ReadTimeout("temporary timeout", request=request)
        return httpx.Response(200, json=[MARKET_RECORD], request=request)

    with make_client(httpx.MockTransport(handle)) as client:
        provider = CoinGeckoMarketMetadataProvider(
            client=client,
            sleep=lambda _: None,
        )
        result = provider.fetch_markets(quote_currency="usd")

    assert len(result) == 1
    assert attempts == 2


def test_invalid_provider_payload_raises_visible_response_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"id": "bitcoin"}], request=request)

    with make_client(httpx.MockTransport(handle)) as client:
        provider = CoinGeckoMarketMetadataProvider(client=client)
        with pytest.raises(CoinGeckoResponseError, match="invalid market metadata"):
            provider.fetch_markets(quote_currency="usd")

    assert any(
        record.message.startswith("Market metadata response validation failed")
        for record in caplog.records
    )


def test_invalid_market_values_are_rejected_during_normalization(
    caplog: pytest.LogCaptureFixture,
) -> None:
    record = {**MARKET_RECORD, "market_cap": -1}

    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[record], request=request)

    with make_client(httpx.MockTransport(handle)) as client:
        provider = CoinGeckoMarketMetadataProvider(client=client)
        with pytest.raises(CoinGeckoResponseError, match="failed normalization"):
            provider.fetch_markets(quote_currency="usd")

    assert any(
        record.message.startswith("Market metadata normalization failed")
        for record in caplog.records
    )


def test_invalid_query_is_rejected_without_provider_call() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        pytest.fail(f"Unexpected provider request: {request.url}")

    with make_client(httpx.MockTransport(handle)) as client:
        provider = CoinGeckoMarketMetadataProvider(client=client)
        with pytest.raises(ValueError, match="per_page"):
            provider.fetch_markets(quote_currency="usd", per_page=251)


def test_provider_factory_uses_secret_settings_and_rejects_unknown_provider() -> None:
    settings = Settings(
        market_metadata_provider="coingecko",
        coingecko_api_key="secret-key",
    )
    requests: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[MARKET_RECORD], request=request)

    with make_client(httpx.MockTransport(handle)) as client:
        provider = create_market_metadata_provider(settings, client=client)
        assert isinstance(provider, CoinGeckoMarketMetadataProvider)
        provider.fetch_markets(quote_currency="usd")
    assert requests[0].headers["x-cg-demo-api-key"] == "secret-key"

    unsupported = Settings(market_metadata_provider="unknown")
    with pytest.raises(ValueError, match="Unsupported market metadata provider"):
        create_market_metadata_provider(unsupported)
