from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from crypto_market_insights.candle_storage import create_database_engine
from crypto_market_insights.dependencies import get_risk_decision_repository
from crypto_market_insights.main import app
from crypto_market_insights.risk_gates import (
    RISK_GATE_STRATEGY_VERSION,
    RiskGateEvaluator,
    RiskGateInput,
    RiskGatePolicy,
)
from crypto_market_insights.risk_storage import (
    RiskDecisionRepository,
    risk_metadata,
)

EVALUATED_AT = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


def make_input(**overrides: object) -> RiskGateInput:
    values: dict[str, object] = {
        "candidate_asset_id": "bitcoin",
        "venue": "Kraken",
        "venue_pair": "XBT/USD",
        "pair_mapping_status": "resolved",
        "evaluated_at": EVALUATED_AT,
        "latest_completed_close_time": EVALUATED_AT - timedelta(hours=1),
        "latest_completed_candle_count": 300,
        "required_candle_count": 200,
        "quote_volume": Decimal("50000000"),
        "liquidity_score": Decimal(80),
        "close_price": Decimal("100"),
        "atr": Decimal("10"),
        "gross_reward_risk": Decimal("2"),
        "fee_bps": Decimal(10),
        "slippage_bps": Decimal(10),
        "severe_event_status": "none",
        "positive_sentiment_score": Decimal(100),
        "timeframes_aligned": True,
        "invalidation_price": Decimal("88"),
        "setup_expiry": EVALUATED_AT + timedelta(hours=24),
    }
    values.update(overrides)
    return RiskGateInput(**values)


def test_safe_candidate_is_approved_with_post_cost_reward_risk() -> None:
    result = RiskGateEvaluator().evaluate(make_input())

    assert result.outcome == "TRADE"
    assert result.approved is True
    assert result.reasons == ()
    assert result.post_cost_reward_risk == Decimal("1.996")
    assert result.strategy_version == RISK_GATE_STRATEGY_VERSION


def test_no_trade_reports_machine_and_human_reasons_for_all_rejections() -> None:
    result = RiskGateEvaluator().evaluate(
        make_input(
            latest_completed_close_time=EVALUATED_AT - timedelta(hours=30),
            latest_completed_candle_count=20,
            required_candle_count=200,
            venue_pair=None,
            pair_mapping_status="uncertain",
            quote_volume=Decimal("100"),
            liquidity_score=Decimal(10),
            atr=Decimal("30"),
            gross_reward_risk=Decimal("1"),
            severe_event_status="unresolved",
            timeframes_aligned=False,
            invalidation_price=None,
        )
    )

    assert result.outcome == "NO_TRADE"
    assert result.approved is False
    codes = {reason.code for reason in result.reasons}
    assert codes >= {
        "stale_candle",
        "missing_candle_history",
        "uncertain_pair_mapping",
        "poor_liquidity",
        "abnormal_volatility",
        "poor_post_cost_reward_risk",
        "unresolved_severe_event",
        "timeframes_misaligned",
        "undefined_invalidation",
    }
    assert all(reason.message for reason in result.reasons)


def test_positive_sentiment_cannot_override_unresolved_severe_event() -> None:
    result = RiskGateEvaluator().evaluate(
        make_input(
            severe_event_status="unresolved",
            positive_sentiment_score=Decimal(100),
        )
    )

    assert result.outcome == "NO_TRADE"
    assert [reason.code for reason in result.reasons] == ["unresolved_severe_event"]


def test_missing_and_future_candle_data_are_explicit_rejections() -> None:
    missing = RiskGateEvaluator().evaluate(make_input(latest_completed_close_time=None))
    future = RiskGateEvaluator().evaluate(
        make_input(latest_completed_close_time=EVALUATED_AT + timedelta(hours=1))
    )

    assert "missing_completed_candle" in {reason.code for reason in missing.reasons}
    assert "future_candle" in {reason.code for reason in future.reasons}


def test_volatility_and_post_cost_reward_risk_use_configured_limits() -> None:
    policy = RiskGatePolicy(
        max_atr_to_close=Decimal("0.10"),
        min_post_cost_reward_risk=Decimal("2"),
        setup_expiry=timedelta(hours=12),
    )
    result = RiskGateEvaluator(policy).evaluate(
        make_input(
            atr=Decimal("12"),
            gross_reward_risk=Decimal("1.90"),
            setup_expiry=EVALUATED_AT + timedelta(hours=12),
        )
    )

    assert {reason.code for reason in result.reasons} == {
        "abnormal_volatility",
        "poor_post_cost_reward_risk",
    }
    assert result.expires_at == EVALUATED_AT + timedelta(hours=12)


def test_missing_post_cost_reward_risk_and_invalid_expiry_are_rejected() -> None:
    result = RiskGateEvaluator().evaluate(
        make_input(
            gross_reward_risk=None,
            setup_expiry=EVALUATED_AT,
        )
    )

    assert {reason.code for reason in result.reasons} == {
        "reward_risk_input_missing",
        "invalid_setup_expiry",
    }


def test_repository_persists_trade_and_no_trade_decisions() -> None:
    engine = create_database_engine("sqlite:///:memory:")
    risk_metadata.create_all(engine)
    repository = RiskDecisionRepository(engine)
    trade = RiskGateEvaluator().evaluate(make_input())
    no_trade = RiskGateEvaluator().evaluate(
        make_input(
            evaluated_at=EVALUATED_AT + timedelta(hours=1),
            latest_completed_close_time=EVALUATED_AT,
            setup_expiry=EVALUATED_AT + timedelta(hours=25),
            severe_event_status="unresolved",
        )
    )

    trade_id = repository.persist(trade)
    no_trade_id = repository.persist(no_trade)
    latest = repository.get_latest(candidate_asset_id="bitcoin")
    history = repository.get_history(candidate_asset_id="bitcoin")

    assert trade_id != no_trade_id
    assert latest is not None
    assert latest["outcome"] == "NO_TRADE"
    assert latest["reasons"][0]["code"] == "unresolved_severe_event"
    assert len(history) == 2
    with engine.connect() as connection:
        event_count = connection.execute(select(risk_metadata.tables["risk_decision_events"])).all()
    assert len(event_count) == 1
    engine.dispose()


def test_repository_rejects_out_of_order_decisions() -> None:
    engine = create_database_engine("sqlite:///:memory:")
    risk_metadata.create_all(engine)
    repository = RiskDecisionRepository(engine)
    first = RiskGateEvaluator().evaluate(make_input())
    repository.persist(first)

    with pytest.raises(ValueError, match="in increasing time order"):
        repository.persist(first)
    engine.dispose()


def test_risk_decision_api_persists_and_returns_no_trade() -> None:
    engine = create_database_engine("sqlite:///:memory:")
    risk_metadata.create_all(engine)
    repository = RiskDecisionRepository(engine)
    app.dependency_overrides[get_risk_decision_repository] = lambda: repository
    try:
        response = TestClient(app).post(
            "/api/v1/risk-gates/evaluate",
            json={
                "candidate_asset_id": "bitcoin",
                "venue": "kraken",
                "venue_pair": "XBT/USD",
                "pair_mapping_status": "resolved",
                "evaluated_at": EVALUATED_AT.isoformat(),
                "latest_completed_close_time": (EVALUATED_AT - timedelta(hours=1)).isoformat(),
                "latest_completed_candle_count": 300,
                "required_candle_count": 200,
                "quote_volume": "50000000",
                "liquidity_score": "80",
                "close_price": "100",
                "atr": "10",
                "gross_reward_risk": "2",
                "fee_bps": "10",
                "slippage_bps": "10",
                "severe_event_status": "unresolved",
                "positive_sentiment_score": "100",
                "timeframes_aligned": True,
                "invalidation_price": "88",
                "setup_expiry": (EVALUATED_AT + timedelta(hours=24)).isoformat(),
            },
        )
        latest = TestClient(app).get(
            "/api/v1/risk-gates/latest",
            params={"candidate_asset_id": "bitcoin"},
        )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 200
    assert response.json()["outcome"] == "NO_TRADE"
    assert response.json()["reasons"][0]["code"] == "unresolved_severe_event"
    assert latest.status_code == 200
