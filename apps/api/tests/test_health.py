from pytest import MonkeyPatch

from crypto_market_insights.config import Settings
from crypto_market_insights.health import health_check


def test_health_check_reports_ready_service() -> None:
    assert health_check() == {
        "service": "crypto-market-insights",
        "status": "ok",
    }


def test_settings_load_from_environment(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("UNIVERSE_SIZE", "3")

    settings = Settings()

    assert settings.app_env == "test"
    assert settings.universe_size == 3
