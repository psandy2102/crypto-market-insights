from pytest import MonkeyPatch

from crypto_market_insights.config import Settings
from crypto_market_insights.health import health_check
from crypto_market_insights.main import get_health


def test_health_check_reports_ready_service() -> None:
    assert health_check() == {
        "service": "crypto-market-insights",
        "status": "ok",
    }


def test_api_health_endpoint_reports_ready_service() -> None:
    assert get_health() == {
        "service": "crypto-market-insights",
        "status": "ok",
    }


def test_settings_load_from_environment(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("UNIVERSE_SIZE", "3")
    monkeypatch.setenv("COINGECKO_API_KEY", "test-secret")

    settings = Settings()

    assert settings.app_env == "test"
    assert settings.universe_size == 3
    assert settings.coingecko_api_key is not None
    assert settings.coingecko_api_key.get_secret_value() == "test-secret"
    assert "test-secret" not in repr(settings)
