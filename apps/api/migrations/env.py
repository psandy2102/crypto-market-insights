"""Alembic environment for candle ingestion persistence."""

import os

from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

config = context.config
database_url = os.environ.get(
    "DATABASE_URL",
    config.get_main_option("sqlalchemy.url"),
).replace("postgresql://", "postgresql+psycopg://", 1)


def run_migrations_offline() -> None:
    """Render migration SQL without opening a database connection."""
    context.configure(
        url=database_url,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations using a database connection."""
    engine = create_engine(database_url, poolclass=NullPool)
    with engine.connect() as connection:
        if connection.dialect.name != "postgresql":
            raise RuntimeError("Candle ingestion migrations require PostgreSQL.")
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
