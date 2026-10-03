from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

# We use SQLite for development ease
# SQLite async requires 'aiosqlite'
async_db_url = "sqlite+aiosqlite:///./stackwise.db"

engine = create_async_engine(async_db_url, echo=True)
AsyncSessionLocal = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

Base = declarative_base()

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
