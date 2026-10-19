"""Async SQLAlchemy engine, session factory and the FastAPI session dependency.

The URL comes from `SQLALCHEMY_URL` (default: the local SQLite file). Point it at
PostgreSQL — `postgresql+asyncpg://…`, the driver `requirements.txt` pins — to run
the same code against Supabase/Postgres; the models already use the Postgres
`UUID` dialect. Alembic reads the same setting and translates it to its
synchronous driver, so runtime and migrations cannot drift apart.

A hosted pooler is handled here instead of being documented as a trap: see
`uses_transaction_pooler`.
"""

from typing import Any

from sqlalchemy import event, make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import settings

#: Ports a hosted Postgres pooler uses for *transaction* pooling: Supabase's
#: `…pooler.supabase.com:6543`, and pgbouncer's usual port elsewhere. A *session*
#: pooler listens on 5432 and pins a server connection per client, so it behaves
#: like a direct connection.
_TRANSACTION_POOLER_PORTS = frozenset({6543})


def uses_transaction_pooler(url: str, mode: str = "auto") -> bool:
    """Whether `url` goes through a transaction-mode pooler.

    Such a pooler hands each transaction — in practice each statement outside one
    — to whichever server connection is free, so a prepared statement created on
    one is missing on the next: asyncpg then fails with `prepared statement
    "__asyncpg_stmt_1__" does not exist`, which reads as a code bug rather than as
    a connection-pooler configuration. `mode` is the `SQLALCHEMY_POOL_MODE`
    setting; `auto` reads the answer off the port. Only PostgreSQL URLs can be
    pooled this way.
    """
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql":
        return False
    if mode == "transaction":
        return True
    if mode == "direct":
        return False
    return parsed.port in _TRANSACTION_POOLER_PORTS


def engine_options(url: str) -> dict[str, Any]:
    """The arguments the async engine is created with.

    `pool_pre_ping` is unconditional: a pooled connection can be closed by the
    server or by a pooler between requests, and one `SELECT 1` is cheaper than the
    first request after an idle period failing.
    """
    options: dict[str, Any] = {"echo": settings.SQLALCHEMY_ECHO, "pool_pre_ping": True}
    if uses_transaction_pooler(url, settings.SQLALCHEMY_POOL_MODE):
        # Nothing is held between requests and neither prepared-statement cache is
        # used: SQLAlchemy's own and asyncpg's (both are connection arguments).
        options |= {
            "poolclass": NullPool,
            "connect_args": {"statement_cache_size": 0, "prepared_statement_cache_size": 0},
        }
    return options


engine = create_async_engine(settings.SQLALCHEMY_URL, **engine_options(settings.SQLALCHEMY_URL))


if engine.dialect.name == "sqlite":

    @event.listens_for(engine.sync_engine, "connect")
    def _enforce_sqlite_foreign_keys(dbapi_connection, _record):
        """Make SQLite enforce `ON DELETE CASCADE`, as Postgres does.

        SQLite ships with `foreign_keys` OFF, so the DDL's `ondelete="CASCADE"`
        was inert: a core `delete(Project)` — which cannot cascade through the
        ORM — left its `analysis_runs` and their `findings` behind as orphan
        rows. Every connection turns it on, so the two databases the project
        supports agree on what a delete means.
        """
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

# expire_on_commit=False keeps attributes readable after `commit()` so endpoints
# can return an ORM object without a second SELECT.
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()


async def get_db():
    """One session per request, always closed when the request ends."""
    async with AsyncSessionLocal() as session:
        yield session
