from io import StringIO
from pathlib import Path

from alembic import command
from alembic.config import Config


def test_candle_ingestion_migration_renders_constraints() -> None:
    config_path = Path(__file__).resolve().parents[1] / "alembic.ini"
    output = StringIO()
    config = Config(str(config_path), output_buffer=output)

    command.upgrade(config, "head", sql=True)
    sql = output.getvalue()

    for expected in (
        "CREATE TABLE candle_ingestion_runs",
        "CREATE TABLE candles",
        "CREATE TABLE candle_provider_health",
        "CREATE TABLE universe_runs",
        "CREATE TABLE universe_memberships",
        "CREATE TABLE universe_rankings",
        "CREATE TABLE risk_decisions",
        "CREATE TABLE risk_decision_events",
        "CREATE TABLE news_feed_runs",
        "CREATE TABLE news_feed_health",
        "CREATE TABLE news_articles",
        "CREATE TABLE news_article_sources",
        "risk_decisions_outcome_check",
        "risk_decisions_consistency_check",
        "asset_types JSONB NOT NULL",
        "universe_membership_run_asset_unique",
        "universe_ranking_run_asset_unique",
        "ranking_strategy_version",
        "effective_from",
        "effective_to",
        "candles_unique_key",
        "CREATE UNIQUE INDEX candles_unique_key ON candles "
        "(venue, venue_pair, interval, open_time)",
        "NUMERIC(38, 18)",
        "TIMESTAMP WITH TIME ZONE",
        "candle_ingestion_runs_failed_idx",
    ):
        assert expected in sql
