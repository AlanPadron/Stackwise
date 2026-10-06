import pytest
import asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app

@pytest.mark.asyncio
async def test_full_auth_flow():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        email = f"user_{asyncio.get_event_loop().time()}@example.com"
        password = "testpassword123"

        # 1. Sign Up
        reg_res = await client.post("/api/v1/auth/register", json={"email": email, "password": password})
        assert reg_res.status_code == 201
        
        # 2. Login
        login_data = {"username": email, "password": password}
        login_res = await client.post("/api/v1/auth/login", data=login_data)
        assert login_res.status_code == 200
        token = login_res.json()["access_token"]
        
        # 3. Get Me
        me_res = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me_res.status_code == 200
        assert me_res.json()["email"] == email

@pytest.mark.asyncio
async def test_login_invalid_credentials():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        login_data = {"username": "nonexistent@example.com", "password": "wrongpassword"}
        res = await client.post("/api/v1/auth/login", data=login_data)
        assert res.status_code == 401

@pytest.mark.asyncio
async def test_duplicate_registration():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        email = f"dup_{asyncio.get_event_loop().time()}@example.com"
        password = "password123"
        await client.post("/api/v1/auth/register", json={"email": email, "password": password})
        res = await client.post("/api/v1/auth/register", json={"email": email, "password": password})
        assert res.status_code == 400
