import asyncio
from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.models.user import User
from app.models.project import Project
from app.models.analysis import AnalysisRun
from app.core.security import get_password_hash
import uuid

async def create_admin():
    async with AsyncSessionLocal() as session:
        # Check if admin already exists
        result = await session.execute(select(User).where(User.email == "admin@stackwise.com"))
        if result.scalar_one_or_none():
            print("Admin user already exists.")
            return

        hashed_password = get_password_hash("1234")
        admin = User(
            id=uuid.uuid4(),
            email="admin@stackwise.com",
            password_hash=hashed_password
        )
        session.add(admin)
        await session.commit()
        print("Admin user created successfully!")
        print("Email: admin@stackwise.com")
        print("Password: 1234")

if __name__ == "__main__":
    asyncio.run(create_admin())
