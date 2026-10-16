"""Accounts: registration, sign-in and what both refuse.

The shape of the suite is: one happy path end to end, then one test per rule the
endpoints are supposed to enforce. Those rules live in `app/core/security.py`
(policy, canonical email) and `app/core/ratelimit.py` (per-address and
per-account limits), so the unit tests below and the endpoint tests are checking
the same code from two directions.
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core import security
from app.core.config import settings
from app.core.ratelimit import reset_auth_limiters
from app.main import app

# A password that satisfies the policy. Deliberately not a realistic secret: it
# only has to pass `password_problem`.
GOOD_PASSWORD = "Probe-pass-2024"

WEAK_PASSWORDS = {
    "too short": "Ab1",
    "no digit": "onlyletters",
    "no letter": "1234567890",
    "common base": "Password-1234",
    "common base with padding": "Qwerty-2024",
    "the product name": "stackwise-2024",
    "longer than bcrypt reads": "Aa1" + "x" * 70,
}


def _register_payload(password: str = GOOD_PASSWORD) -> dict:
    return {"email": f"user_{uuid.uuid4().hex}@example.com", "password": password}


# --- unit --------------------------------------------------------------------


@pytest.mark.parametrize("case", list(WEAK_PASSWORDS))
def test_policy_rejects_weak_passwords(case):
    assert security.password_problem(WEAK_PASSWORDS[case]) is not None


def test_policy_accepts_a_reasonable_password():
    assert security.password_problem(GOOD_PASSWORD) is None
    # 72 bytes is the boundary bcrypt reads up to, so it is allowed.
    assert security.password_problem("Aa1" + "x" * 69) is None


def test_normalize_email_lowercases_and_trims():
    assert security.normalize_email("  Mixed.Case@Example.COM ") == "mixed.case@example.com"


def test_dummy_hash_is_a_real_bcrypt_hash():
    """The unknown-address path must pay the same price as a real check."""
    assert security.DUMMY_PASSWORD_HASH.startswith("$2b$12$")
    assert len(security.DUMMY_PASSWORD_HASH) == 60
    security.verify_against_dummy("whatever")  # must not raise


# --- HTTP --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_auth_flow(client):
    payload = _register_payload()
    registered = await client.post("/api/v1/auth/register", json=payload)
    assert registered.status_code == 201

    login = await client.post(
        "/api/v1/auth/login",
        data={"username": payload["email"], "password": payload["password"]},
    )
    assert login.status_code == 200

    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == payload["email"]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", list(WEAK_PASSWORDS))
async def test_weak_password_is_refused_at_signup(client, case):
    response = await client.post("/api/v1/auth/register", json=_register_payload(WEAK_PASSWORDS[case]))
    assert response.status_code == 422
    # The reason reaches the SPA, which is what shows it under the field.
    assert "password" in response.text.lower()


@pytest.mark.asyncio
async def test_login_invalid_credentials(client):
    response = await client.post(
        "/api/v1/auth/login", data={"username": "nobody@example.com", "password": "wrongpassword"}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_unknown_email_and_wrong_password_are_indistinguishable(client):
    """Same status and same body: the endpoint must not confirm an address."""
    email = _register_payload()["email"]
    await client.post("/api/v1/auth/register", json={"email": email, "password": GOOD_PASSWORD})

    unknown = await client.post(
        "/api/v1/auth/login", data={"username": "absent@example.com", "password": GOOD_PASSWORD}
    )
    wrong = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": "Wrong-pass-2024"}
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


@pytest.mark.asyncio
async def test_duplicate_registration(client):
    payload = _register_payload()
    assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 201
    assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 400


@pytest.mark.asyncio
async def test_email_casing_does_not_create_a_second_account(client):
    email = f"Mixed_{uuid.uuid4().hex[:8]}@Example.com"
    created = await client.post("/api/v1/auth/register", json={"email": email, "password": GOOD_PASSWORD})
    assert created.status_code == 201
    assert created.json()["email"] == email.lower()

    # Same account, whichever casing is typed at sign-in.
    login = await client.post(
        "/api/v1/auth/login",
        data={"username": email.upper(), "password": GOOD_PASSWORD},
    )
    assert login.status_code == 200

    # And the address cannot be registered again in another casing.
    again = await client.post(
        "/api/v1/auth/register", json={"email": email.upper(), "password": GOOD_PASSWORD}
    )
    assert again.status_code == 400


@pytest.mark.asyncio
async def test_login_is_rate_limited_atomically(client, monkeypatch):
    """The lockout follows the account, not just the address.

    Login is counted per address *and* per account, so a burst against one
    account is refused even from a fresh address, while a different account from
    that same address still works.
    """
    monkeypatch.setattr(settings, "AUTH_LOGIN_RATE_LIMIT_PER_MINUTE", 3)
    reset_auth_limiters()

    victim = _register_payload()["email"]
    await client.post("/api/v1/auth/register", json={"email": victim, "password": GOOD_PASSWORD})

    for _ in range(3):
        response = await client.post(
            "/api/v1/auth/login", data={"username": victim, "password": "Wrong-pass-2024"}
        )
        assert response.status_code == 401

    blocked = await client.post(
        "/api/v1/auth/login", data={"username": victim, "password": "Wrong-pass-2024"}
    )
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1

    # Same account, another address: still locked, because the account key is
    # shared across addresses.
    async with AsyncClient(
        transport=ASGITransport(app=app, client=("10.0.0.7", 40000)), base_url="http://test"
    ) as elsewhere:
        assert (
            await elsewhere.post(
                "/api/v1/auth/login", data={"username": victim, "password": GOOD_PASSWORD}
            )
        ).status_code == 429

        # A different account from that address is served normally.
        other = _register_payload()["email"]
        await elsewhere.post(
            "/api/v1/auth/register", json={"email": other, "password": GOOD_PASSWORD}
        )
        assert (
            await elsewhere.post(
                "/api/v1/auth/login", data={"username": other, "password": GOOD_PASSWORD}
            )
        ).status_code == 200


@pytest.mark.asyncio
async def test_signup_is_rate_limited_per_address(client, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_REGISTER_RATE_LIMIT_PER_MINUTE", 2)
    reset_auth_limiters()

    assert (await client.post("/api/v1/auth/register", json=_register_payload())).status_code == 201
    assert (await client.post("/api/v1/auth/register", json=_register_payload())).status_code == 201

    blocked = await client.post("/api/v1/auth/register", json=_register_payload())
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) >= 1
