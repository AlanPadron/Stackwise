"""OAuth sign-in and the GitHub repository import.

The provider round-trip is stubbed at the service boundary (`exchange_code` /
`fetch_identity` / the GitHub calls) so the flow under test is *our* code: state
handling, account resolution, linking and the import pipeline.
"""

import tempfile
import uuid
import zipfile
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core import security
from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.main import app
from app.models.oauth import OAuthAccount
from app.services import github as github_service
from app.services import oauth as oauth_service
from app.services.oauth import Identity, OAuthError


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _configure(monkeypatch, provider: str = "google") -> None:
    """Give a provider credentials for the duration of one test."""
    monkeypatch.setattr(settings, f"{provider.upper()}_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(settings, f"{provider.upper()}_CLIENT_SECRET", "test-client-secret")


def _stub_provider(monkeypatch, identity: Identity, access_token: str = "provider-token") -> None:
    async def exchange_code(provider, code, code_verifier):
        return {"access_token": access_token, "scope": provider.scope}

    async def fetch_identity(provider, token):
        return identity

    monkeypatch.setattr(oauth_service, "exchange_code", exchange_code)
    monkeypatch.setattr(oauth_service, "fetch_identity", fetch_identity)


def _pkce(
    provider: str = "google",
    link_user_id: str | None = None,
    next_path: str | None = None,
) -> tuple[str, dict[str, str]]:
    """A signed `state` plus the `Cookie` header its callback needs.

    Both halves are required to reach the callback: the challenge travels inside
    the signed state (as it does through the provider) and the verifier in an
    HttpOnly cookie, which is what a browser would send back.
    Returned explicitly instead of pushed into the client's jar: a test that runs
    two round-trips on one client would otherwise carry a stale verifier next to
    the fresh one, and which of them the server reads is jar order.
    """
    verifier = security.new_code_verifier()
    state = security.create_oauth_state(
        provider,
        link_user_id,
        next_path,
        code_challenge=security.code_challenge(verifier),
    )
    return state, {security.OAUTH_PKCE_COOKIE: verifier}


async def _authorize_url(
    client: AsyncClient, provider: str = "google", headers: dict | None = None, **params
) -> str:
    response = await client.get(
        f"/api/v1/auth/oauth/{provider}/authorize", params=params, headers=headers
    )
    assert response.status_code == 200, response.text
    return response.json()["authorization_url"]


async def _me(client: AsyncClient, token: str) -> dict:
    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _token_from_redirect(response) -> str:
    """Pull the session token out of the `Location` fragment."""
    assert response.status_code == 302, response.text
    fragment = parse_qs(urlparse(response.headers["location"]).fragment)
    assert "token" in fragment, response.headers["location"]
    return fragment["token"][0]


# --- provider availability ---------------------------------------------------


@pytest.mark.asyncio
async def test_providers_reports_configuration(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "")
    monkeypatch.setattr(settings, "DEV_OAUTH_MOCK", False)
    _configure(monkeypatch, "github")

    async with _client() as client:
        response = await client.get("/api/v1/auth/providers")

    assert response.status_code == 200
    assert response.json() == {"google": False, "github": True, "mock": False}


@pytest.mark.asyncio
async def test_authorize_rejects_unconfigured_provider(monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "")

    async with _client() as client:
        response = await client.get("/api/v1/auth/oauth/google/authorize")

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_authorize_rejects_unknown_provider(monkeypatch):
    _configure(monkeypatch)

    async with _client() as client:
        response = await client.get("/api/v1/auth/oauth/bitbucket/authorize")

    assert response.status_code == 404


# --- the authorization URL ---------------------------------------------------


@pytest.mark.asyncio
async def test_authorize_builds_provider_url_with_signed_state(monkeypatch):
    _configure(monkeypatch, "github")

    async with _client() as client:
        url = await _authorize_url(client, "github", next="/projects/import")

    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.netloc == "github.com"
    assert query["client_id"] == ["test-client-id"]
    assert query["scope"] == [oauth_service.PROVIDERS["github"].scope]
    assert query["redirect_uri"] == [
        f"{settings.API_PUBLIC_URL}/api/v1/auth/oauth/github/callback"
    ]

    claims = security.read_oauth_state(query["state"][0])
    assert claims["provider"] == "github"
    assert claims["next"] == "/projects/import"
    assert claims["link_user_id"] is None


@pytest.mark.asyncio
async def test_authorize_drops_offsite_next(monkeypatch):
    """`next` must never become an open redirect."""
    _configure(monkeypatch)

    async with _client() as client:
        url = await _authorize_url(client, "google", next="https://evil.example.com")

    claims = security.read_oauth_state(parse_qs(urlparse(url).query)["state"][0])
    assert claims["next"] is None


@pytest.mark.asyncio
async def test_authorize_links_when_signed_in(monkeypatch):
    _configure(monkeypatch, "github")
    email = f"linker_{uuid.uuid4().hex}@example.com"

    async with _client() as client:
        await client.post(
            "/api/v1/auth/register", json={"email": email, "password": "Probe-pass-2024"}
        )
        login = await client.post(
            "/api/v1/auth/login", data={"username": email, "password": "Probe-pass-2024"}
        )
        token = login.json()["access_token"]

        url = await _authorize_url(
            client, "github", headers={"Authorization": f"Bearer {token}"}
        )

    claims = security.read_oauth_state(parse_qs(urlparse(url).query)["state"][0])
    assert claims["link_user_id"] is not None


# --- the callback ------------------------------------------------------------


@pytest.mark.asyncio
async def test_callback_creates_account_and_returns_session(monkeypatch):
    _configure(monkeypatch)
    identity = Identity(provider_user_id=uuid.uuid4().hex, email=f"gh_{uuid.uuid4().hex}@example.com", login="octocat")
    _stub_provider(monkeypatch, identity, access_token="gh-token")
    async with _client() as client:
        state, pkce = _pkce("google", next_path="/dashboard")
        response = await client.get(
            "/api/v1/auth/oauth/google/callback",
            params={"code": "auth-code", "state": state},
            cookies=pkce,
        )
        me = await _me(client, _token_from_redirect(response))

    assert me["email"] == identity.email
    assert parse_qs(urlparse(response.headers["location"]).fragment)["next"] == ["/dashboard"]

    # The provider token must be stored: it is the credential the repo import uses.
    async with AsyncSessionLocal() as db:
        account = (
            await db.execute(
                select(OAuthAccount).where(
                    OAuthAccount.provider_user_id == identity.provider_user_id
                )
            )
        ).scalar_one()
        assert account.access_token == "gh-token"
        assert account.provider_login == "octocat"


@pytest.mark.asyncio
async def test_callback_is_idempotent_for_the_same_identity(monkeypatch):
    _configure(monkeypatch)
    identity = Identity(provider_user_id=uuid.uuid4().hex, email=f"gh_{uuid.uuid4().hex}@example.com")
    _stub_provider(monkeypatch, identity)

    async with _client() as client:
        first_state, first_pkce = _pkce()
        second_state, second_pkce = _pkce()
        first = await client.get(
            "/api/v1/auth/oauth/google/callback",
            params={"code": "c1", "state": first_state},
            cookies=first_pkce,
        )
        second = await client.get(
            "/api/v1/auth/oauth/google/callback",
            params={"code": "c2", "state": second_state},
            cookies=second_pkce,
        )
        first_me = await _me(client, _token_from_redirect(first))
        second_me = await _me(client, _token_from_redirect(second))

    assert first_me["id"] == second_me["id"]


@pytest.mark.asyncio
async def test_callback_links_an_existing_password_account(monkeypatch):
    _configure(monkeypatch)
    email = f"both_{uuid.uuid4().hex}@example.com"
    _stub_provider(monkeypatch, Identity(provider_user_id=uuid.uuid4().hex, email=email))

    async with _client() as client:
        registered = await client.post(
            "/api/v1/auth/register", json={"email": email, "password": "Probe-pass-2024"}
        )
        user_id = registered.json()["id"]

        state, pkce = _pkce()
        response = await client.get(
            "/api/v1/auth/oauth/google/callback",
            params={"code": "c", "state": state},
            cookies=pkce,
        )
        me = await _me(client, _token_from_redirect(response))

        # The original password still works: the account was linked, not replaced.
        login = await client.post(
            "/api/v1/auth/login", data={"username": email, "password": "Probe-pass-2024"}
        )

    assert me["id"] == user_id
    assert login.status_code == 200


@pytest.mark.asyncio
async def test_oauth_only_account_cannot_use_password_login(monkeypatch):
    _configure(monkeypatch)
    email = f"onlyoauth_{uuid.uuid4().hex}@example.com"
    _stub_provider(monkeypatch, Identity(provider_user_id=uuid.uuid4().hex, email=email))

    async with _client() as client:
        state, pkce = _pkce()
        await client.get(
            "/api/v1/auth/oauth/google/callback",
            params={"code": "c", "state": state},
            cookies=pkce,
        )
        login = await client.post(
            "/api/v1/auth/login", data={"username": email, "password": security.UNUSABLE_PASSWORD}
        )

    assert login.status_code == 401


@pytest.mark.asyncio
async def test_callback_rejects_a_forged_state(monkeypatch):
    _configure(monkeypatch)
    _stub_provider(monkeypatch, Identity(provider_user_id="1", email="x@example.com"))

    async with _client() as client:
        response = await client.get(
            "/api/v1/auth/oauth/google/callback",
            params={"code": "c", "state": "not-a-signed-state"},
        )

    assert response.status_code == 302
    assert parse_qs(urlparse(response.headers["location"]).fragment)["error"] == ["state"]


@pytest.mark.asyncio
async def test_callback_rejects_a_state_for_another_provider(monkeypatch):
    _configure(monkeypatch)
    _configure(monkeypatch, "github")
    _stub_provider(monkeypatch, Identity(provider_user_id="1", email="x@example.com"))

    async with _client() as client:
        state, pkce = _pkce("github")
        response = await client.get(
            "/api/v1/auth/oauth/google/callback",
            params={"code": "c", "state": state},
            cookies=pkce,
        )

    assert parse_qs(urlparse(response.headers["location"]).fragment)["error"] == ["state"]


@pytest.mark.asyncio
async def test_callback_reports_a_provider_failure(monkeypatch):
    _configure(monkeypatch)

    async def failing_exchange(provider, code, code_verifier):
        raise OAuthError("nope")

    monkeypatch.setattr(oauth_service, "exchange_code", failing_exchange)

    async with _client() as client:
        state, pkce = _pkce()
        response = await client.get(
            "/api/v1/auth/oauth/google/callback",
            params={"code": "c", "state": state},
            cookies=pkce,
        )

    assert parse_qs(urlparse(response.headers["location"]).fragment)["error"] == ["provider"]


@pytest.mark.asyncio
async def test_callback_refuses_to_steal_a_linked_identity(monkeypatch):
    _configure(monkeypatch)
    identity = Identity(provider_user_id=uuid.uuid4().hex, email=f"own_{uuid.uuid4().hex}@example.com")
    _stub_provider(monkeypatch, identity)

    async with _client() as client:
        # First user owns the provider identity.
        first_state, first_pkce = _pkce()
        await client.get(
            "/api/v1/auth/oauth/google/callback",
            params={"code": "c", "state": first_state},
            cookies=first_pkce,
        )

        # A second user asks to link the same identity.
        email = f"thief_{uuid.uuid4().hex}@example.com"
        await client.post(
            "/api/v1/auth/register", json={"email": email, "password": "Probe-pass-2024"}
        )
        login = await client.post(
            "/api/v1/auth/login", data={"username": email, "password": "Probe-pass-2024"}
        )
        token = login.json()["access_token"]
        url = await _authorize_url(
            client, "google", headers={"Authorization": f"Bearer {token}"}
        )
        state = parse_qs(urlparse(url).query)["state"][0]

        response = await client.get(
            "/api/v1/auth/oauth/google/callback", params={"code": "c", "state": state}
        )

    assert parse_qs(urlparse(response.headers["location"]).fragment)["error"] == ["link"]


# --- PKCE (RFC 7636) ---------------------------------------------------------


@pytest.mark.asyncio
async def test_authorize_hands_the_browser_a_verifier(monkeypatch):
    """The challenge goes to the provider; the verifier stays in a cookie here."""
    _configure(monkeypatch)

    async with _client() as client:
        response = await client.get("/api/v1/auth/oauth/google/authorize")
        verifier = response.cookies.get(security.OAUTH_PKCE_COOKIE)

    url = response.json()["authorization_url"]
    query = parse_qs(urlparse(url).query)
    assert verifier is not None and 43 <= len(verifier) <= 128
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] == [security.code_challenge(verifier)]


@pytest.mark.asyncio
async def test_callback_sends_the_verifier_to_the_token_endpoint(monkeypatch):
    """The endpoint that exchanges the code gets the verifier the challenge came from."""
    _configure(monkeypatch)
    seen: dict[str, str] = {}

    async def exchange_code(provider, code, code_verifier):
        seen["verifier"] = code_verifier
        return {"access_token": "t", "scope": provider.scope}

    async def fetch_identity(provider, token):
        return Identity(provider_user_id=uuid.uuid4().hex, email=f"pkce_{uuid.uuid4().hex}@example.com")

    monkeypatch.setattr(oauth_service, "exchange_code", exchange_code)
    monkeypatch.setattr(oauth_service, "fetch_identity", fetch_identity)

    async with _client() as client:
        url = await _authorize_url(client, "google")
        query = parse_qs(urlparse(url).query)
        response = await client.get(
            "/api/v1/auth/oauth/google/callback",
            params={"code": "c", "state": query["state"][0]},
        )

    assert response.status_code == 302
    assert seen["verifier"]
    # The verifier the token endpoint receives hashes to the challenge the
    # provider was given: that is what makes an intercepted code useless.
    assert security.code_challenge(seen["verifier"]) == query["code_challenge"][0]


@pytest.mark.asyncio
async def test_callback_requires_the_verifier_cookie(monkeypatch):
    """A code replayed from another browser (or stolen) never becomes a session."""
    _configure(monkeypatch)
    _stub_provider(monkeypatch, Identity(provider_user_id="1", email="x@example.com"))

    async with _client() as client:
        state, _ = _pkce()

        # The code arrives in a browser that never started the flow: no verifier.
        response = await client.get(
            "/api/v1/auth/oauth/google/callback", params={"code": "c", "state": state}
        )

    assert response.status_code == 302
    assert parse_qs(urlparse(response.headers["location"]).fragment)["error"] == ["pkce"]


@pytest.mark.asyncio
async def test_callback_rejects_a_verifier_that_does_not_match(monkeypatch):
    _configure(monkeypatch)
    _stub_provider(monkeypatch, Identity(provider_user_id="1", email="x@example.com"))

    async with _client() as client:
        state, _ = _pkce()
        # A verifier this browser was never handed.
        wrong = {security.OAUTH_PKCE_COOKIE: security.new_code_verifier()}

        response = await client.get(
            "/api/v1/auth/oauth/google/callback",
            params={"code": "c", "state": state},
            cookies=wrong,
        )

    assert parse_qs(urlparse(response.headers["location"]).fragment)["error"] == ["pkce"]


# --- connected accounts ------------------------------------------------------


async def _password_user(client: AsyncClient) -> str:
    """A signed-in account that also has a password; returns its bearer token."""
    email = f"links_{uuid.uuid4().hex}@example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": "Probe-pass-2024"})
    login = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": "Probe-pass-2024"}
    )
    return login.json()["access_token"]


async def _link(client: AsyncClient, provider: str, token: str) -> None:
    """Attach a provider to the signed-in account, the way the SPA does it."""
    url = await _authorize_url(client, provider, headers={"Authorization": f"Bearer {token}"})
    state = parse_qs(urlparse(url).query)["state"][0]
    response = await client.get(
        f"/api/v1/auth/oauth/{provider}/callback", params={"code": "c", "state": state}
    )
    _token_from_redirect(response)


@pytest.mark.asyncio
async def test_links_lists_a_connection_and_unlink_removes_it(monkeypatch):
    _configure(monkeypatch)
    identity = Identity(
        provider_user_id=uuid.uuid4().hex, email=f"listed_{uuid.uuid4().hex}@example.com", login="octocat"
    )
    _stub_provider(monkeypatch, identity)

    async with _client() as client:
        token = await _password_user(client)
        headers = {"Authorization": f"Bearer {token}"}
        assert (await client.get("/api/v1/auth/oauth/links", headers=headers)).json() == []

        await _link(client, "google", token)
        listed = (await client.get("/api/v1/auth/oauth/links", headers=headers)).json()
        removed = await client.delete("/api/v1/auth/oauth/links/google", headers=headers)
        after = (await client.get("/api/v1/auth/oauth/links", headers=headers)).json()

    assert [row["provider"] for row in listed] == ["google"]
    assert listed[0]["login"] == "octocat"
    assert listed[0]["email"] == identity.email
    # The provider token is what the API uses for imports; the browser never sees it.
    assert "access_token" not in listed[0]
    assert removed.status_code == 204
    assert after == []


@pytest.mark.asyncio
async def test_unlink_refuses_to_remove_the_last_way_in(monkeypatch):
    _configure(monkeypatch)
    _configure(monkeypatch, "github")
    google = Identity(provider_user_id=uuid.uuid4().hex, email=f"only_{uuid.uuid4().hex}@example.com")
    _stub_provider(monkeypatch, google)

    async with _client() as client:
        # An account created by signing in with a provider carries no password.
        url = await _authorize_url(client, "google")
        state = parse_qs(urlparse(url).query)["state"][0]
        response = await client.get(
            "/api/v1/auth/oauth/google/callback", params={"code": "c", "state": state}
        )
        headers = {"Authorization": f"Bearer {_token_from_redirect(response)}"}

        refused = await client.delete("/api/v1/auth/oauth/links/google", headers=headers)

        # With a second identity attached, the first one can go.
        github = Identity(provider_user_id=uuid.uuid4().hex, email=f"second_{uuid.uuid4().hex}@example.com")
        _stub_provider(monkeypatch, github)
        await _link(client, "github", headers["Authorization"].split(" ", 1)[1])
        allowed = await client.delete("/api/v1/auth/oauth/links/google", headers=headers)

    assert refused.status_code == 409
    assert allowed.status_code == 204


@pytest.mark.asyncio
async def test_unlink_rejects_unknown_and_unlinked_providers(monkeypatch):
    _configure(monkeypatch)

    async with _client() as client:
        token = await _password_user(client)
        headers = {"Authorization": f"Bearer {token}"}
        unknown = await client.delete("/api/v1/auth/oauth/links/myspace", headers=headers)
        unlinked = await client.delete("/api/v1/auth/oauth/links/google", headers=headers)
        anonymous = await client.delete("/api/v1/auth/oauth/links/google")

    assert unknown.status_code == 404
    assert unlinked.status_code == 404
    assert anonymous.status_code == 401


@pytest.mark.asyncio
async def test_unlink_revokes_the_provider_token(monkeypatch):
    """Disconnecting must not leave a working credential at the provider."""
    _configure(monkeypatch)
    identity = Identity(provider_user_id=uuid.uuid4().hex, email=f"rev_{uuid.uuid4().hex}@example.com")
    _stub_provider(monkeypatch, identity, access_token="gh-token")
    revoked: list[tuple[str, str]] = []

    async def revoke_token(provider, access_token):
        revoked.append((provider.name, access_token))

    monkeypatch.setattr(oauth_service, "revoke_token", revoke_token)

    async with _client() as client:
        token = await _password_user(client)
        await _link(client, "google", token)
        response = await client.delete(
            "/api/v1/auth/oauth/links/google", headers={"Authorization": f"Bearer {token}"}
        )

    assert response.status_code == 204
    assert revoked == [("google", "gh-token")]


# --- the development-only mock provider --------------------------------------


@pytest.mark.asyncio
async def test_mock_provider_is_off_unless_enabled(monkeypatch):
    monkeypatch.setattr(settings, "DEV_OAUTH_MOCK", False)

    async with _client() as client:
        providers = await client.get("/api/v1/auth/providers")
        authorize = await client.get("/api/v1/auth/oauth/mock/authorize")
        consent = await client.get(
            "/api/v1/auth/oauth/mock/consent", params={"state": "irrelevant"}
        )

    assert providers.json()["mock"] is False
    assert authorize.status_code == 503
    assert consent.status_code == 503


@pytest.mark.asyncio
async def test_mock_provider_signs_in_end_to_end(monkeypatch):
    monkeypatch.setattr(settings, "DEV_OAUTH_MOCK", True)

    async with _client() as client:
        providers = await client.get("/api/v1/auth/providers")
        url = await _authorize_url(client, "mock", next="/dashboard")

        # The "provider" is a consent screen served by this API.
        consent = await client.get(url)
        assert consent.status_code == 200
        assert oauth_service.MOCK_IDENTITY.email in consent.text
        assert f"code={oauth_service.MOCK_CODE}" in consent.text

        state = parse_qs(urlparse(url).query)["state"][0]
        response = await client.get(
            "/api/v1/auth/oauth/mock/callback",
            params={"code": oauth_service.MOCK_CODE, "state": state},
        )
        me = await _me(client, _token_from_redirect(response))

    assert providers.json()["mock"] is True
    assert me["email"] == oauth_service.MOCK_IDENTITY.email
    assert me["email"].endswith("@example.com")


@pytest.mark.asyncio
async def test_mock_provider_rejects_a_foreign_code(monkeypatch):
    monkeypatch.setattr(settings, "DEV_OAUTH_MOCK", True)

    async with _client() as client:
        mock_state, mock_pkce = _pkce("mock")
        response = await client.get(
            "/api/v1/auth/oauth/mock/callback",
            params={"code": "not-the-mock-code", "state": mock_state},
            cookies=mock_pkce,
        )

    assert parse_qs(urlparse(response.headers["location"]).fragment)["error"] == ["provider"]


@pytest.mark.asyncio
async def test_mock_provider_cancel_is_reported(monkeypatch):
    monkeypatch.setattr(settings, "DEV_OAUTH_MOCK", True)

    async with _client() as client:
        mock_state, mock_pkce = _pkce("mock")
        response = await client.get(
            "/api/v1/auth/oauth/mock/callback",
            params={"error": "access_denied", "state": mock_state},
            cookies=mock_pkce,
        )

    assert parse_qs(urlparse(response.headers["location"]).fragment)["error"] == ["denied"]


@pytest.mark.asyncio
async def test_real_provider_cancel_is_reported_too(monkeypatch):
    """A refusal from a real provider sends `error` and no `code`."""
    _configure(monkeypatch)

    async with _client() as client:
        state, pkce = _pkce()
        response = await client.get(
            "/api/v1/auth/oauth/google/callback",
            params={"error": "access_denied", "state": state},
            cookies=pkce,
        )

    assert response.status_code == 302
    assert parse_qs(urlparse(response.headers["location"]).fragment)["error"] == ["denied"]


# --- GitHub repositories -----------------------------------------------------


async def _register(client: AsyncClient) -> tuple[dict, dict]:
    email = f"gh_user_{uuid.uuid4().hex}@example.com"
    registered = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": "Probe-pass-2024"}
    )
    login = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": "Probe-pass-2024"}
    )
    return registered.json(), {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _link_github(user_id: str, token: str = "gh-token") -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            OAuthAccount(
                user_id=uuid.UUID(user_id),
                provider="github",
                provider_user_id=uuid.uuid4().hex,
                provider_login="octocat",
                access_token=token,
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_repositories_reports_not_connected():
    async with _client() as client:
        _, headers = await _register(client)
        response = await client.get("/api/v1/github/repositories", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"connected": False, "login": None, "repositories": []}


@pytest.mark.asyncio
async def test_repositories_lists_the_connected_account(monkeypatch):
    async def list_repositories(token):
        assert token == "gh-token"
        return [
            {
                "full_name": "octocat/hello-world",
                "name": "hello-world",
                "owner": "octocat",
                "private": False,
                "description": "demo",
                "default_branch": "main",
                "language": "Python",
                "updated_at": "2026-01-01T00:00:00Z",
                "html_url": "https://github.com/octocat/hello-world",
            }
        ]

    monkeypatch.setattr(github_service, "list_repositories", list_repositories)

    async with _client() as client:
        user, headers = await _register(client)
        await _link_github(user["id"])
        response = await client.get("/api/v1/github/repositories", headers=headers)

    body = response.json()
    assert body["connected"] is True
    assert body["login"] == "octocat"
    assert body["repositories"][0]["full_name"] == "octocat/hello-world"


@pytest.mark.asyncio
async def test_repositories_surfaces_a_github_failure(monkeypatch):
    async def failing(token):
        raise github_service.GitHubError("GitHub rejected the repository list (401)", 401)

    monkeypatch.setattr(github_service, "list_repositories", failing)

    async with _client() as client:
        user, headers = await _register(client)
        await _link_github(user["id"])
        response = await client.get("/api/v1/github/repositories", headers=headers)

    assert response.status_code == 502


# --- importing a repository --------------------------------------------------


def _repository_zip() -> str:
    """A real ZIP with one lintable Python file, as GitHub's zipball would give."""
    path = tempfile.NamedTemporaryFile(delete=False, suffix=".zip").name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("hello-world-main/app.py", "import os\n\n\ndef f():\n    return 1\n")
    return path


@pytest.mark.asyncio
async def test_import_requires_a_github_connection():
    async with _client() as client:
        _, headers = await _register(client)
        response = await client.post(
            "/api/v1/projects/from-repo",
            json={"repository": "octocat/hello-world"},
            headers=headers,
        )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_import_creates_a_project_and_runs_the_analysis(monkeypatch):
    async def download(token, full_name, ref=None):
        assert full_name == "octocat/hello-world"
        return _repository_zip()

    monkeypatch.setattr(github_service, "download_repository_zip", download)

    async with _client() as client:
        user, headers = await _register(client)
        await _link_github(user["id"])
        response = await client.post(
            "/api/v1/projects/from-repo",
            json={"repository": "octocat/hello-world"},
            headers=headers,
        )

        assert response.status_code == 201, response.text
        body = response.json()

        # The background task has already run by the time ASGITransport returns.
        run = await client.get(f"/api/v1/analyses/{body['run']['id']}", headers=headers)
        findings = await client.get(
            f"/api/v1/analyses/{body['run']['id']}/findings", headers=headers
        )

    assert body["project"]["name"] == "hello-world"
    assert body["run"]["source_type"] == "github"
    assert run.json()["status"] == "completed"
    # `import os` is unused, so ruff must report at least one finding.
    assert len(findings.json()) >= 1


@pytest.mark.asyncio
async def test_import_maps_a_missing_repository_to_404(monkeypatch):
    async def download(token, full_name, ref=None):
        raise github_service.GitHubError("Could not download nope/nope (404)", 404)

    monkeypatch.setattr(github_service, "download_repository_zip", download)

    async with _client() as client:
        user, headers = await _register(client)
        await _link_github(user["id"])
        response = await client.post(
            "/api/v1/projects/from-repo",
            json={"repository": "nope/nope"},
            headers=headers,
        )

    assert response.status_code == 404


# --- password sentinel -------------------------------------------------------


def test_unusable_password_never_verifies():
    assert security.verify_password("", security.UNUSABLE_PASSWORD) is False
    assert security.verify_password(security.UNUSABLE_PASSWORD, security.UNUSABLE_PASSWORD) is False
    assert security.verify_password("Probe-pass-2024", "") is False
