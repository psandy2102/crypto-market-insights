from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from crypto_market_insights.candle_storage import create_database_engine
from crypto_market_insights.config import Settings
from crypto_market_insights.dependencies import get_universe_repository
from crypto_market_insights.main import app
from crypto_market_insights.market_metadata import AssetMarketMetadata
from crypto_market_insights.universe import (
    RANKING_STRATEGY_VERSION,
    RankingComponents,
    RankingEvidence,
    RankingStrategy,
    UniverseObservation,
    UniversePolicy,
    UniverseService,
    rank_candidates,
    select_universe,
)
from crypto_market_insights.universe_storage import (
    UniverseRepository,
    universe_memberships,
    universe_metadata,
)

AS_OF = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


def make_observation(
    asset_id: str,
    symbol: str,
    market_cap: int,
    *,
    quote_volume: int = 100,
    venue_pair: str | None = "__auto__",
    venue: str = "kraken",
    history_timeframe: str = "1d",
    asset_types: frozenset[str] = frozenset(),
    history_count: int = 5,
    metadata_age: timedelta = timedelta(hours=1),
    retrieval_age: timedelta | None = None,
    history_age: timedelta = timedelta(hours=1),
    quality: str = "95",
    canonical_asset_id: str | None = None,
    evaluated_at: datetime = AS_OF,
) -> UniverseObservation:
    source_time = evaluated_at - metadata_age
    metadata = AssetMarketMetadata(
        provider="coingecko",
        provider_asset_id=asset_id,
        canonical_asset_id=canonical_asset_id or asset_id,
        symbol=symbol,
        name=f"{symbol} asset",
        current_price=Decimal(10),
        market_cap=Decimal(market_cap),
        market_cap_rank=None,
        total_volume=Decimal(quote_volume),
        source_timestamp=source_time,
        retrieved_at=evaluated_at - (retrieval_age or metadata_age),
    )
    return UniverseObservation(
        metadata=metadata,
        venue=venue,
        quote_currency="USD",
        history_timeframe=history_timeframe,
        venue_pair=f"{symbol}/USD" if venue_pair == "__auto__" else venue_pair,
        asset_types=asset_types,
        history_candle_count=history_count,
        history_as_of=evaluated_at - history_age,
        data_quality_score=Decimal(quality) if quality else None,
    )


def make_policy(**overrides: Any) -> UniversePolicy:
    values: dict[str, Any] = {
        "size": 2,
        "quote_currency": "USD",
        "min_market_cap": Decimal(50),
        "min_quote_volume": Decimal(25),
        "min_history_candles": 5,
        "max_metadata_age": timedelta(hours=24),
        "max_history_age": timedelta(hours=26),
        "min_data_quality": Decimal(80),
    }
    values.update(overrides)
    return UniversePolicy(**values)


def make_selection(*, evaluated_at: datetime = AS_OF):
    observations = [
        make_observation("bitcoin", "BTC", 1000, evaluated_at=evaluated_at),
        make_observation("ethereum", "ETH", 900, evaluated_at=evaluated_at),
    ]
    return select_universe(
        observations,
        venue="Kraken",
        quote_currency="usd",
        evaluated_at=evaluated_at,
        policy=make_policy(),
    )


def make_components(value: str = "50") -> RankingComponents:
    score = Decimal(value)
    return RankingComponents(
        trend_alignment=score,
        momentum_relative_strength=score,
        volume_confirmation=score,
        setup_quality=score,
        liquidity_quality=score,
        news_context=score,
    )


def test_universe_selects_by_market_cap_and_excludes_ineligible_assets() -> None:
    observations = [
        make_observation("smaller", "SMOL", 700),
        make_observation("largest", "LARGE", 1000),
        make_observation("stable", "USDT", 9000),
        make_observation("wrapped", "WBTC", 8000),
        make_observation("leveraged", "BTC3L", 7000),
        make_observation("stale", "STALE", 600, metadata_age=timedelta(days=2)),
        make_observation("low-volume", "LOW", 500, quote_volume=2),
        make_observation("short-history", "SHORT", 400, history_count=2),
        make_observation("poor-quality", "POOR", 300, quality="20"),
        make_observation("unsupported", "UNSUPPORTED", 200, venue_pair=None),
        make_observation("wrong-timeframe", "WRONG", 150, history_timeframe="1h"),
        make_observation("low-cap", "LOWCAP", 20),
        make_observation(
            "classified-stable",
            "CUSTOMUSD",
            10000,
            asset_types=frozenset({"stablecoin"}),
        ),
        make_observation(
            "classified-bridge",
            "CUSTOMBTC",
            10000,
            asset_types=frozenset({"bridged"}),
        ),
        make_observation(
            "classified-synthetic",
            "SYNTH",
            10000,
            asset_types=frozenset({"synthetic"}),
        ),
    ]

    result = select_universe(
        observations,
        venue="kraken",
        quote_currency="USD",
        evaluated_at=AS_OF,
        policy=make_policy(),
    )

    assert result.selected_asset_ids == ("largest", "smaller")
    assert [candidate.selection_rank for candidate in result.selected] == [1, 2]
    reasons = {
        candidate.provider_asset_id: candidate.exclusion_reasons for candidate in result.candidates
    }
    assert reasons["stable"] == ("stablecoin",)
    assert "wrapped_or_bridged_asset" in reasons["wrapped"]
    assert "leveraged_token" in reasons["leveraged"]
    assert "stale_metadata" in reasons["stale"]
    assert "quote_volume_below_minimum" in reasons["low-volume"]
    assert "insufficient_history" in reasons["short-history"]
    assert "data_quality_below_minimum" in reasons["poor-quality"]
    assert "unsupported_venue_pair" in reasons["unsupported"]
    assert "history_timeframe_mismatch" in reasons["wrong-timeframe"]
    assert reasons["classified-stable"] == ("stablecoin",)
    assert reasons["classified-bridge"] == ("wrapped_or_bridged_asset",)
    assert reasons["classified-synthetic"] == ("synthetic_asset",)
    assert "market_cap_below_minimum" in reasons["low-cap"]
    assert all(candidate.effective_from == AS_OF for candidate in result.selected)


def test_universe_rejects_stale_retrieval_even_when_source_timestamp_is_recent() -> None:
    observation = make_observation(
        "old-retrieval",
        "OLD",
        500,
        metadata_age=timedelta(hours=1),
        retrieval_age=timedelta(days=2),
    )

    result = select_universe(
        [observation],
        venue="kraken",
        quote_currency="USD",
        evaluated_at=AS_OF,
        policy=make_policy(),
    )

    assert result.selected_asset_ids == ()
    assert result.candidates[0].exclusion_reasons == ("stale_metadata",)


def test_universe_rejects_asset_without_current_price() -> None:
    observation = make_observation("no-price", "NOPRICE", 500)
    observation = observation.model_copy(
        update={"metadata": observation.metadata.model_copy(update={"current_price": None})}
    )

    result = select_universe(
        [observation],
        venue="kraken",
        quote_currency="USD",
        evaluated_at=AS_OF,
        policy=make_policy(),
    )

    assert result.selected_asset_ids == ()
    assert result.candidates[0].exclusion_reasons == ("missing_current_price",)


def test_universe_caps_membership_but_retains_eligible_unselected_candidates() -> None:
    result = select_universe(
        [
            make_observation("first", "AAA", 1000),
            make_observation("second", "BBB", 900),
            make_observation("third", "CCC", 800),
        ],
        venue="kraken",
        quote_currency="USD",
        evaluated_at=AS_OF,
        policy=make_policy(size=2),
    )

    third = next(
        candidate for candidate in result.candidates if candidate.provider_asset_id == "third"
    )
    assert third.eligible is True
    assert third.selected is False
    assert third.effective_from is None
    assert result.selected_asset_ids == ("first", "second")


def test_universe_rejects_duplicate_provider_ids_and_mismatched_quote_currency() -> None:
    observation = make_observation("bitcoin", "BTC", 1000)
    with pytest.raises(ValueError, match="only once"):
        select_universe(
            [observation, observation],
            venue="kraken",
            quote_currency="USD",
            evaluated_at=AS_OF,
            policy=make_policy(),
        )

    euro_observation = observation.model_copy(update={"quote_currency": "EUR"})
    with pytest.raises(ValueError, match="expected 'USD'"):
        select_universe(
            [euro_observation],
            venue="kraken",
            quote_currency="USD",
            evaluated_at=AS_OF,
            policy=make_policy(),
        )


def test_universe_rejects_future_data_and_deduplicates_canonical_exposures() -> None:
    future = make_observation(
        "future",
        "FUTURE",
        1000,
        metadata_age=timedelta(hours=-1),
        history_age=timedelta(hours=-1),
    )
    duplicate = make_observation(
        "same-exposure",
        "BTCLIKE",
        900,
    )
    result = select_universe(
        [
            make_observation("bitcoin", "BTC", 1100),
            duplicate,
            future,
        ],
        venue="kraken",
        quote_currency="USD",
        evaluated_at=AS_OF,
        policy=make_policy(canonical_asset_overrides={"same-exposure": "bitcoin"}),
    )

    by_id = {candidate.provider_asset_id: candidate for candidate in result.candidates}
    assert "metadata_from_future" in by_id["future"].exclusion_reasons
    assert "history_from_future" in by_id["future"].exclusion_reasons
    assert by_id["same-exposure"].eligible is False
    assert by_id["same-exposure"].exclusion_reasons == ("duplicate_exposure:bitcoin",)
    assert result.selected_asset_ids == ("bitcoin",)


def test_universe_requires_explicit_evaluation_timestamp_and_matching_quote() -> None:
    with pytest.raises(ValueError, match="timezone"):
        select_universe(
            [],
            venue="kraken",
            quote_currency="USD",
            evaluated_at=datetime(2026, 11, 14),
            policy=make_policy(),
        )
    with pytest.raises(ValueError, match="does not match"):
        select_universe(
            [],
            venue="kraken",
            quote_currency="EUR",
            evaluated_at=AS_OF,
            policy=make_policy(),
        )


def test_ranking_applies_documented_weights_and_returns_components() -> None:
    selection = make_selection()
    components = RankingComponents(
        trend_alignment=Decimal(100),
        momentum_relative_strength=Decimal(80),
        volume_confirmation=Decimal(60),
        setup_quality=Decimal(40),
        liquidity_quality=Decimal(20),
        news_context=Decimal(0),
    )
    result = rank_candidates(
        selection,
        {
            "bitcoin": RankingEvidence(components=components),
            "ethereum": RankingEvidence(components=make_components("50")),
        },
    )

    assert result.strategy_version == RANKING_STRATEGY_VERSION
    assert result.weights == RankingStrategy.COMPONENT_WEIGHTS
    assert result.entries[0].provider_asset_id == "bitcoin"
    assert result.entries[0].component_scores == components
    assert result.entries[0].total_score == Decimal("60.00")
    assert result.entries[0].rank == 1
    assert result.entries[1].total_score == Decimal("50.00")
    assert result.entries[1].rank == 2
    assert result.no_trade is False


def test_ranking_gates_candidates_and_does_not_replace_missing_evidence() -> None:
    selection = make_selection()
    result = rank_candidates(
        selection,
        {"bitcoin": RankingEvidence(components=make_components(), gate_failures=("stale_data",))},
    )

    assert result.entries[0].gate_failures == ("stale_data",)
    assert result.entries[0].rank is None
    assert result.entries[1].gate_failures == ("missing_ranking_evidence",)
    assert result.entries[1].component_scores is None
    assert result.no_trade is True


def test_ranking_rejects_evidence_for_assets_outside_selected_universe() -> None:
    with pytest.raises(ValueError, match="outside the selected universe"):
        rank_candidates(
            make_selection(),
            {"not-selected": RankingEvidence(components=make_components())},
        )


def test_universe_policy_loads_configured_screening_thresholds() -> None:
    policy = UniversePolicy.from_settings(
        Settings(
            universe_size=4,
            universe_min_market_cap=Decimal(500),
            universe_min_quote_volume=Decimal(50),
            universe_min_history_candles=20,
            universe_history_timeframe="4h",
            universe_max_metadata_age_hours=12,
            universe_max_history_age_hours=18,
            universe_min_data_quality=Decimal(85),
        )
    )

    assert policy.size == 4
    assert policy.min_market_cap == Decimal(500)
    assert policy.min_quote_volume == Decimal(50)
    assert policy.min_history_candles == 20
    assert policy.history_timeframe == "4h"
    assert policy.max_metadata_age == timedelta(hours=12)
    assert policy.max_history_age == timedelta(hours=18)
    assert policy.min_data_quality == Decimal(85)


def test_repository_persists_effective_membership_and_rank_component_values() -> None:
    selection = make_selection()
    ranking = rank_candidates(
        selection,
        {
            "bitcoin": RankingEvidence(components=make_components("80")),
            "ethereum": RankingEvidence(components=make_components("60")),
        },
    )
    engine = create_database_engine("sqlite:///:memory:")
    universe_metadata.create_all(engine)
    repository = UniverseRepository(engine)

    run_id = repository.persist(selection, ranking)
    stored = repository.get_latest(venue="kraken")

    assert stored is not None
    assert str(stored["run"]["id"]) == str(run_id)
    assert stored["run"]["universe_version"] == "universe-v1"
    assert stored["run"]["ranking_strategy_version"] == RANKING_STRATEGY_VERSION
    assert len(stored["candidates"]) == 2
    assert all(candidate["effective_from"] == AS_OF for candidate in stored["candidates"])
    assert stored["rankings"][0]["component_scores"]["trend_alignment"] == Decimal(80)
    assert stored["rankings"][0]["total_score"] == Decimal("80.00")
    assert stored["rankings"][0]["rank"] == 1
    engine.dispose()


def test_universe_service_selects_scores_and_persists_as_one_operation() -> None:
    engine = create_database_engine("sqlite:///:memory:")
    universe_metadata.create_all(engine)
    repository = UniverseRepository(engine)
    observations = [
        make_observation("bitcoin", "BTC", 1000),
        make_observation("ethereum", "ETH", 900),
    ]

    evaluation = UniverseService(repository).evaluate(
        observations,
        {
            "bitcoin": RankingEvidence(components=make_components("80")),
            "ethereum": RankingEvidence(components=make_components("60")),
        },
        venue="kraken",
        quote_currency="USD",
        evaluated_at=AS_OF,
        policy=make_policy(),
    )

    stored = repository.get_latest(venue="kraken")
    assert stored is not None
    assert str(stored["run"]["id"]) == str(evaluation.run_id)
    assert evaluation.selection.selected_asset_ids == ("bitcoin", "ethereum")
    assert evaluation.ranking.entries[0].rank == 1
    engine.dispose()


def test_repository_closes_previous_membership_and_rejects_out_of_order_runs() -> None:
    engine = create_database_engine("sqlite:///:memory:")
    universe_metadata.create_all(engine)
    repository = UniverseRepository(engine)
    first_selection = make_selection()
    first_ranking = rank_candidates(
        first_selection,
        {
            "bitcoin": RankingEvidence(components=make_components()),
            "ethereum": RankingEvidence(components=make_components()),
        },
    )
    repository.persist(first_selection, first_ranking)

    later = AS_OF + timedelta(days=1)
    second_selection = make_selection(evaluated_at=later)
    second_ranking = rank_candidates(
        second_selection,
        {
            "bitcoin": RankingEvidence(components=make_components()),
            "ethereum": RankingEvidence(components=make_components()),
        },
    )
    repository.persist(second_selection, second_ranking)

    with engine.connect() as connection:
        rows = (
            connection.execute(
                select(universe_memberships).order_by(universe_memberships.c.effective_from)
            )
            .mappings()
            .all()
        )
    assert len(rows) == 4
    assert all(row["effective_to"].replace(tzinfo=UTC) == later for row in rows[:2])
    assert all(row["effective_to"] is None for row in rows[2:])
    with pytest.raises(ValueError, match="in increasing time order"):
        repository.persist(first_selection, first_ranking)
    engine.dispose()


def test_repository_enforces_time_order_even_after_a_no_trade_snapshot() -> None:
    engine = create_database_engine("sqlite:///:memory:")
    universe_metadata.create_all(engine)
    repository = UniverseRepository(engine)
    observation = make_observation("stable", "USDT", 10000)
    selection = select_universe(
        [observation],
        venue="kraken",
        quote_currency="USD",
        evaluated_at=AS_OF,
        policy=make_policy(),
    )
    ranking = rank_candidates(selection, {})

    assert selection.selected_asset_ids == ()
    assert ranking.no_trade is True
    repository.persist(selection, ranking)
    with pytest.raises(ValueError, match="in increasing time order"):
        repository.persist(selection, ranking)
    engine.dispose()


def test_latest_universe_endpoint_exposes_rankings_and_returns_404_when_empty() -> None:
    engine = create_database_engine("sqlite:///:memory:")
    universe_metadata.create_all(engine)
    repository = UniverseRepository(engine)
    app.dependency_overrides[get_universe_repository] = lambda: repository
    try:
        client = TestClient(app)
        assert client.get("/api/v1/universe/latest").status_code == 404

        selection = make_selection()
        ranking = rank_candidates(
            selection,
            {
                "bitcoin": RankingEvidence(components=make_components("80")),
                "ethereum": RankingEvidence(components=make_components("60")),
            },
        )
        repository.persist(selection, ranking)
        response = client.get("/api/v1/universe/latest?venue=kraken")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 200
    body = response.json()
    assert body["run"]["ranking_strategy_version"] == RANKING_STRATEGY_VERSION
    assert body["rankings"][0]["component_scores"]["trend_alignment"] == 80
    assert body["rankings"][0]["rank"] == 1
