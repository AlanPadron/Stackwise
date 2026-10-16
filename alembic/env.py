"""Alembic environment.

The migration URL is taken from the application settings (`SQLALCHEMY_URL`), not
from `alembic.ini`, so `alembic upgrade head` always targets the same database the
app talks to. Async driver URLs are translated to their synchronous equivalents,
because Alembic runs plain SQLAlchemy engines:

    sqlite+aiosqlite:///./stackwise.db  →  sqlite:///./stackwise.db
    postgresql+asyncpg://…              →  postgresql+psycopg2://…

`ALEMBIC_DATABASE_URL` overrides everything (used by the migration tests).
"""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine.url import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.db.base import Base  # noqa: E402  (imports every model)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

_SYNC_DRIVERS = {
    "sqlite+aiosqlite": "sqlite",
    "postgresql+asyncpg": "postgresql+psycopg2",
    "postgresql+psycopg": "postgresql+psycopg2",
}


def _database_url() -> str:
    raw = os.environ.get("ALEMBIC_DATABASE_URL") or settings.SQLALCHEMY_URL
    url = make_url(raw)
    return url.set(drivername=_SYNC_DRIVERS.get(url.drivername, url.drivername)).render_as_string(
        hide_password=False
    )


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
