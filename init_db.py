import asyncio
from app.db.session import engine, Base

async def init_db():
    async with engine.begin() as conn:
        # This creates all tables defined in Base
        # We need to import models first so they are registered with Base
        from app.models.user import User
        from app.models.project import Project
        from app.models.analysis import AnalysisRun
        
        await conn.run_sync(Base.metadata.create_all)
    print("Database initialized successfully!")

if __name__ == "__main__":
    asyncio.run(init_db())
