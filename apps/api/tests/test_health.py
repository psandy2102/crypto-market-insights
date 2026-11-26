from decimal import Decimal

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
    monkeypatch.setenv("RISK_MIN_POST_COST_REWARD_RISK", "2.25")
    monkeypatch.setenv("RISK_MAX_ATR_TO_CLOSE", "0.15")
    monkeypatch.setenv("RSS_FEEDS", "reuters=https://example.com/rss")
    monkeypatch.setenv("NEWS_EXCERPT_CHARS", "300")

    settings = Settings()

    assert settings.app_env == "test"
    assert settings.universe_size == 3
    assert settings.risk_min_post_cost_reward_risk == Decimal("2.25")
    assert settings.risk_max_atr_to_close == Decimal("0.15")
    assert settings.rss_feeds == "reuters=https://example.com/rss"
    assert settings.news_excerpt_chars == 300
    assert settings.coingecko_api_key is not None
    assert settings.coingecko_api_key.get_secret_value() == "test-secret"
    assert "test-secret" not in repr(settings)
