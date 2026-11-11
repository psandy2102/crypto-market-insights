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
        "candles_unique_key",
        "CREATE UNIQUE INDEX candles_unique_key ON candles "
        "(venue, venue_pair, interval, open_time)",
        "NUMERIC(38, 18)",
        "TIMESTAMP WITH TIME ZONE",
        "candle_ingestion_runs_failed_idx",
    ):
        assert expected in sql
