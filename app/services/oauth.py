"""OAuth2 authorization-code flows for the external identity providers.

Both providers are plain authorization-code flows, so everything provider
specific is data (endpoints, scope, how to read the identity document) and the
endpoints in `app/api/v1/oauth.py` stay provider-agnostic.

A provider is optional: without a client id/secret in the environment it is
reported as disabled and its button stays hidden in the SPA.
"""

import uuid
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import normalize_email
from app.models.oauth import OAuthAccount

HTTP_TIMEOUT = 15.0


class OAuthError(Exception):
    """A provider round-trip that did not produce a usable identity."""


class LinkConflict(Exception):
    """The provider account is already attached to a different local user."""


@dataclass(frozen=True)
class Identity:
    """What the API needs from a provider account, normalised."""

    provider_user_id: str
    email: str
    login: Optional[str] = None


@dataclass(frozen=True)
class Provider:
    name: str
    authorize_url: str
    token_url: str
    scope: str
    # Names of the `Settings` fields holding the credentials, so adding a
    # provider means adding one entry here and nothing else.
    client_id_setting: str = ""
    client_secret_setting: str = ""
    # A local stand-in for a provider (see DEV_OAUTH_MOCK): no credentials, no
    # network, and the consent screen is served by this API.
    is_mock: bool = False


PROVIDERS: dict[str, Provider] = {
    "google": Provider(
        name="google",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scope="openid email profile",
        client_id_setting="GOOGLE_CLIENT_ID",
        client_secret_setting="GOOGLE_CLIENT_SECRET",
    ),
    "github": Provider(
        name="github",
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        # `repo` is what makes private repositories importable; GitHub has no
        # read-only equivalent, so it is requested explicitly and can be denied
        # at the consent screen (public repositories still work).
        scope="read:user user:email repo",
        client_id_setting="GITHUB_CLIENT_ID",
        client_secret_setting="GITHUB_CLIENT_SECRET",
    ),
    "mock": Provider(
        name="mock",
        authorize_url="",
        token_url="",
        scope="dev",
        is_mock=True,
    ),
}

# --- the development-only mock identity --------------------------------------
# Fixed on purpose: a mock provider must never be able to sign in as, or link
# itself to, a real account. `example.com` is reserved for documentation by RFC
# 2606, so it cannot belong to anyone (and it is the shape pydantic accepts).
MOCK_CODE = "dev-mock-code"
MOCK_ACCESS_TOKEN = "dev-mock-token"
MOCK_IDENTITY = Identity(
    provider_user_id="dev-mock-user",
    email="stackwise-mock@example.com",
    login="mock-dev",
)


def get_provider(name: str) -> Provider:
    provider = PROVIDERS.get(name)
    if provider is None:
        raise OAuthError(f"Unknown provider: {name}")
    return provider


def credentials(provider: Provider) -> tuple[str, str]:
    if provider.is_mock:
        raise OAuthError("The mock provider has no credentials")
    return (
        getattr(settings, provider.client_id_setting),
        getattr(settings, provider.client_secret_setting),
    )


def is_configured(name: str) -> bool:
    provider = PROVIDERS.get(name)
    if provider is None:
        return False
    if provider.is_mock:
        return settings.DEV_OAUTH_MOCK
    client_id, client_secret = credentials(provider)
    return bool(client_id and client_secret)


def configured_providers() -> dict[str, bool]:
    return {name: is_configured(name) for name in PROVIDERS}


def redirect_uri(provider: Provider) -> str:
    """The callback URL; must be registered verbatim in the provider console."""
    return f"{settings.API_PUBLIC_URL}{settings.API_V1_STR}/auth/oauth/{provider.name}/callback"


def callback_url(provider: str, **params: str) -> str:
    """An absolute callback URL with query parameters (used by the mock consent)."""
    return (
        f"{settings.API_PUBLIC_URL}{settings.API_V1_STR}"
        f"/auth/oauth/{provider}/callback?{urlencode(params)}"
    )


def build_authorization_url(provider: Provider, state: str, code_challenge: str) -> str:
    if provider.is_mock:
        # The "provider" is a consent screen served by this API, so the whole
        # round-trip stays on this machine.
        return (
            f"{settings.API_PUBLIC_URL}{settings.API_V1_STR}"
            f"/auth/oauth/{provider.name}/consent?{urlencode({'state': state})}"
        )

    client_id, _ = credentials(provider)
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri(provider),
        "response_type": "code",
        "scope": provider.scope,
        "state": state,
        # PKCE (RFC 7636), S256: the verifier stays in an HttpOnly cookie here, so
        # an intercepted authorization code is useless on its own.
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if provider.name == "google":
        # Show the account chooser instead of silently reusing the last session.
        params["prompt"] = "select_account"
        params["access_type"] = "online"
    return f"{provider.authorize_url}?{urlencode(params)}"


async def exchange_code(provider: Provider, code: str, code_verifier: str) -> dict[str, Any]:
    """Trade the authorization code for the provider's access token."""
    if provider.is_mock:
        if code != MOCK_CODE:
            raise OAuthError("Mock authorization rejected")
        return {"access_token": MOCK_ACCESS_TOKEN, "scope": provider.scope}

    client_id, client_secret = credentials(provider)
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        response = await client.post(
            provider.token_url,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri(provider),
                "code_verifier": code_verifier,
            },
            headers={"Accept": "application/json"},
        )

    if response.status_code != 200:
        raise OAuthError(f"Token exchange failed ({response.status_code})")

    payload = response.json()
    # GitHub answers 200 with an `error` field instead of an HTTP error status.
    if payload.get("error") or not payload.get("access_token"):
        raise OAuthError(f"Token exchange rejected: {payload.get('error', 'no access_token')}")
    return payload


async def revoke_token(provider: Provider, access_token: Optional[str]) -> None:
    """Ask the provider to invalidate a token this API is about to forget.

    Disconnecting an account should not leave a working credential behind on the
    provider's side. Best effort: the caller unlinks locally even when this
    raises, because a live token we no longer track is the worse of the two
    outcomes. `OAuthError` marks a refusal the caller can log.
    """
    if not access_token or provider.is_mock:
        return

    client_id, client_secret = credentials(provider)
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        if provider.name == "github":
            response = await client.delete(
                f"{settings.GITHUB_API_BASE_URL}/applications/{client_id}/token",
                auth=(client_id, client_secret),
                json={"access_token": access_token},
                headers={"Accept": "application/json"},
            )
            # 404 means the token was already gone, which is the desired state.
            if response.status_code not in (204, 404):
                raise OAuthError(f"Token revocation failed ({response.status_code})")
            return

        response = await client.post(
            "https://oauth2.googleapis.com/revoke",
            data={"token": access_token},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        # 400 is Google's answer for a token that is already invalid or unknown.
        if response.status_code not in (200, 400):
            raise OAuthError(f"Token revocation failed ({response.status_code})")


async def fetch_identity(provider: Provider, access_token: str) -> Identity:
    if provider.is_mock:
        if access_token != MOCK_ACCESS_TOKEN:
            raise OAuthError("Mock access token rejected")
        return MOCK_IDENTITY
    if provider.name == "google":
        identity = await _google_identity(access_token)
    elif provider.name == "github":
        identity = await _github_identity(access_token)
    else:
        raise OAuthError(f"Unknown provider: {provider.name}")
    # One casing for an address everywhere it is compared or stored: an account
    # created by signing in with Google as `User@x.com` must be the same account
    # that the password form finds when it types `user@x.com`.
    return Identity(
        provider_user_id=identity.provider_user_id,
        email=normalize_email(identity.email),
        login=identity.login,
    )


async def _get_json(url: str, access_token: str, params: Optional[dict] = None) -> Any:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        response = await client.get(
            url,
            params=params,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )
    if response.status_code != 200:
        raise OAuthError(f"Identity lookup failed ({response.status_code})")
    return response.json()


async def _google_identity(access_token: str) -> Identity:
    profile = await _get_json("https://openidconnect.googleapis.com/v1/userinfo", access_token)
    if not profile.get("email") or not profile.get("email_verified"):
        # Signing in with an unverified address would let it be used to take
        # over a local account that happens to own that email.
        raise OAuthError("Google account has no verified email")
    return Identity(provider_user_id=str(profile["sub"]), email=profile["email"])


async def _github_identity(access_token: str) -> Identity:
    profile = await _get_json(f"{settings.GITHUB_API_BASE_URL}/user", access_token)
    login = profile.get("login") or str(profile.get("id"))
    email = profile.get("email")

    if not email:
        # A private primary address is not exposed on /user; /user/emails is
        # available because the flow asks for `user:email`.
        emails = await _get_json(f"{settings.GITHUB_API_BASE_URL}/user/emails", access_token)
        primary = next((e for e in emails if e.get("primary") and e.get("verified")), None)
        fallback = next((e for e in emails if e.get("verified")), None)
        email = (primary or fallback or {}).get("email")

    if not email:
        # GitHub guarantees this address is unique to the account, which keeps
        # the `users.email` uniqueness constraint meaningful.
        email = f"{login}@users.noreply.github.com"

    return Identity(provider_user_id=str(profile["id"]), email=email, login=login)


# --- account lookups ---------------------------------------------------------


async def find_account_by_identity(
    db: AsyncSession, provider: str, provider_user_id: str
) -> Optional[OAuthAccount]:
    result = await db.execute(
        select(OAuthAccount).where(
            OAuthAccount.provider == provider,
            OAuthAccount.provider_user_id == provider_user_id,
        )
    )
    return result.scalar_one_or_none()


async def find_account_for_user(
    db: AsyncSession, user_id: uuid.UUID, provider: str
) -> Optional[OAuthAccount]:
    """The account a local user has linked for `provider`, if any."""
    result = await db.execute(
        select(OAuthAccount).where(
            OAuthAccount.user_id == user_id,
            OAuthAccount.provider == provider,
        )
    )
    return result.scalars().first()


async def linked_accounts(db: AsyncSession, user_id: uuid.UUID) -> list[OAuthAccount]:
    """Every provider identity attached to one local user, stable order."""
    result = await db.execute(
        select(OAuthAccount)
        .where(OAuthAccount.user_id == user_id)
        .order_by(OAuthAccount.provider)
    )
    return list(result.scalars().all())
