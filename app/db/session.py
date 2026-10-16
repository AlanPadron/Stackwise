"""Async SQLAlchemy engine, session factory and the FastAPI session dependency.

The URL comes from `SQLALCHEMY_URL` (default: the local SQLite file). Point it at
PostgreSQL — `postgresql+asyncpg://…` once that driver is installed — to run the
same code against Supabase/Postgres; the models already use the Postgres `UUID`
dialect. The deployment's `DATABASE_URL` is kept separate because it is the
*sync* URL docker-compose and the platform inject, not an async driver URL.
"""

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.core.config import settings

# echo=True prints every statement; handy while developing, noisy in production.
engine = create_async_engine(settings.SQLALCHEMY_URL, echo=settings.SQLALCHEMY_ECHO)


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
