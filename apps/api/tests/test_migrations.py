from io import StringIO
from pathlib import Path

from alembic import command
from alembic.config import Config


def test_initial_postgres_migration_renders_schema_constraints() -> None:
    repository_root = Path(__file__).resolve().parents[3]
    output = StringIO()
    config = Config(
        str(repository_root / "alembic.ini"),
        output_buffer=output,
    )

    command.upgrade(config, "head", sql=True)
    sql = output.getvalue()

    for expected in (
        "CREATE TABLE assets",
        "CREATE TABLE asset_universe_snapshots",
        "CREATE TABLE asset_universe_members",
        "CREATE TABLE venues",
        "CREATE TABLE market_pairs",
        "CREATE TABLE candles",
        "CREATE TABLE market_snapshots",
        "CREATE TABLE news_sources",
        "CREATE TABLE news_articles",
        "CREATE TABLE article_asset_links",
        "CREATE TABLE feature_snapshots",
        "CREATE TABLE candidate_rankings",
        "CREATE TABLE daily_briefs",
        "CREATE TABLE trade_setups",
        "CREATE TABLE scenario_forecasts",
        "CREATE TABLE analysis_runs",
        "CREATE TABLE strategy_versions",
        "CREATE TABLE model_versions",
        "CREATE TABLE brief_input_references",
        "CREATE TABLE evaluation_results",
        "candles_unique_key",
        "TIMESTAMPTZ",
        "NUMERIC(38, 18)",
        "daily_briefs_append_only",
        "brief_input_references_append_only",
    ):
        assert expected in sql
