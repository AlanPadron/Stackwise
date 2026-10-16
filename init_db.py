import asyncio
from app.db.session import engine, Base

async def init_db():
    async with engine.begin() as conn:
        # `app.db.base` imports every model (users, oauth_accounts, projects,
        # analysis_runs, findings) so `create_all` sees the whole metadata; the
        # explicit import below is the single thing that guarantees it.
        import app.db.base  # noqa: F401
        from app.models.analysis import AnalysisRun  # noqa: F401
        from app.models.oauth import OAuthAccount  # noqa: F401
        from app.models.project import Project  # noqa: F401
        from app.models.user import User  # noqa: F401

        await conn.run_sync(Base.metadata.create_all)
    print("Database initialized successfully!")

if __name__ == "__main__":
    asyncio.run(init_db())
