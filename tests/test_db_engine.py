"""How the async engine is configured for the database the URL names.

The pooler case cannot be discovered from a mocked session: a transaction-mode
pooler silently breaks server-side prepared statements, and what asyncpg raises
(`prepared statement "__asyncpg_stmt_1__" does not exist`) reads like a bug in a
query rather than like a connection-pooler setting. What is pinned here is the
decision and the arguments it implies — `create_async_engine` rejects an argument
its dialect does not know, so building one is a real check of those names.
"""

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.db.session import engine_options, uses_transaction_pooler

#: Supabase's transaction pooler, in the shape the dashboard hands out.
TRANSACTION_POOLER = (
    "postgresql+asyncpg://postgres.abcdefghijklmno:secret"
    "@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"
)
#: The session pooler (same host, 5432) pins a server connection per client, so
#: prepared statements survive it.
SESSION_POOLER = TRANSACTION_POOLER.replace(":6543", ":5432")
DIRECT = "postgresql+asyncpg://postgres:secret@db.abcdefghijklmno.supabase.co:5432/postgres"
SQLITE = "sqlite+aiosqlite:///./stackwise.db"


def test_the_transaction_pooler_is_recognised_by_its_port():
    assert uses_transaction_pooler(TRANSACTION_POOLER) is True
    assert uses_transaction_pooler(SESSION_POOLER) is False
    assert uses_transaction_pooler(DIRECT) is False


def test_the_configured_mode_overrides_the_port():
    assert uses_transaction_pooler(DIRECT, "transaction") is True
    assert uses_transaction_pooler(TRANSACTION_POOLER, "direct") is False


def test_a_non_postgresql_url_is_never_treated_as_a_pooler():
    assert uses_transaction_pooler(SQLITE) is False
    assert uses_transaction_pooler(SQLITE, "transaction") is False


def test_a_transaction_pooler_disables_pooling_and_both_statement_caches():
    options = engine_options(TRANSACTION_POOLER)

    assert options["poolclass"] is NullPool
    assert options["connect_args"] == {
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,
    }


def test_a_direct_connection_keeps_the_default_pool():
    options = engine_options(DIRECT)

    assert set(options) == {"echo", "pool_pre_ping"}
    assert options["pool_pre_ping"] is True


@pytest.mark.parametrize("url", [TRANSACTION_POOLER, SESSION_POOLER, DIRECT])
def test_the_engine_accepts_the_arguments_that_url_implies(url):
    """Fails loudly if one of the argument names stops being the right one."""
    created = create_async_engine(url, **engine_options(url))

    assert created.dialect.name == "postgresql"
