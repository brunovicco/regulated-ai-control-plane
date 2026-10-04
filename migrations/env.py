"""Alembic environment for the production PostgreSQL schema."""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = os.environ.get("REGULAAI_DATABASE_URL")
if database_url is None or not database_url.startswith(("postgresql://", "postgresql+psycopg://")):
    raise RuntimeError("REGULAAI_DATABASE_URL must identify a PostgreSQL database")
config.set_main_option(
    "sqlalchemy.url",
    database_url.replace("postgresql://", "postgresql+psycopg://", 1).replace("%", "%%"),
)


def run_migrations_offline() -> None:
    """Render SQL without opening a database connection."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in one bounded connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args={"connect_timeout": 5, "options": "-c statement_timeout=60000"},
    )
    with connectable.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
