"""OAuth sign-in: start a provider round-trip, then handle the way back.

The flow is the standard authorization-code dance:

1. `GET /auth/oauth/{provider}/authorize` returns the provider URL for the SPA
   to send the browser to (with a signed `state`),
2. the provider sends the browser back to
   `GET /auth/oauth/{provider}/callback` with a `code`,
3. the callback resolves or creates the local account, then hands the browser to
   the SPA with a session token in the URL *fragment* — a fragment is never sent
   to a server and never leaks through `Referer`.
"""

import html
import uuid
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import HTMLResponse, RedirectResponse
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_optional_current_user
from app.core import security
from app.core.config import settings
from app.db.session import get_db
from app.models.oauth import OAuthAccount
from app.models.user import User
from app.schemas.oauth import AuthorizeResponse, ProviderAvailability
from app.services import oauth as oauth_service
from app.services.oauth import Identity, LinkConflict, OAuthError

router = APIRouter()

# Error codes handed back to the SPA, which owns the (translated) wording.
ERROR_STATE = "state"
ERROR_PROVIDER = "provider"
ERROR_LINK = "link"
ERROR_DENIED = "denied"

# The consent screen the mock provider serves in place of an external one.
# Placeholders are replaced (not formatted) so the CSS braces stay untouched.
_MOCK_CONSENT_PAGE = """<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Stackwise — mock provider</title>
    <style>
      body {
        margin: 0;
        min-height: 100vh;
        display: grid;
        place-items: center;
        font: 16px/1.5 -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        background: #eef1f6;
        color: #14181f;
      }
      main {
        width: min(26rem, calc(100vw - 3rem));
        padding: 2rem;
        border-radius: 10px;
        background: rgba(255, 255, 255, 0.68);
        border: 1px solid rgba(15, 23, 42, 0.1);
        box-shadow: 0 2px 6px rgba(15, 23, 42, 0.06),
          0 16px 40px -12px rgba(15, 23, 42, 0.2);
      }
      h1 { margin: 0 0 0.5rem; font-size: 1.25rem; }
      p { margin: 0 0 1.5rem; color: #5a6472; font-size: 0.9rem; }
      a {
        display: block;
        text-align: center;
        padding: 0.75rem 1rem;
        border-radius: 6px;
        text-decoration: none;
        font-weight: 600;
        font-size: 0.9rem;
      }
      .allow { background: #c2410c; color: #fff; margin-bottom: 0.75rem; }
      .deny { color: #5a6472; border: 1px solid rgba(15, 23, 42, 0.1); }
      code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.8rem; }
    </style>
  </head>
  <body>
    <main>
      <h1>Stackwise mock provider</h1>
      <p>
        Development only. Approving signs you in as <code>__EMAIL__</code> —
        no external account, no network request.
      </p>
      <a class="allow" href="__APPROVE__">Authorize</a>
      <a class="deny" href="__DENY__">Cancel</a>
    </main>
  </body>
</html>
"""


@router.get("/providers", response_model=ProviderAvailability)
async def list_providers():
    """Which providers have credentials configured; the SPA hides the rest."""
    return oauth_service.configured_providers()


@router.get("/oauth/{provider}/authorize", response_model=AuthorizeResponse)
async def authorize(
    provider: str,
    next: str | None = Query(None, max_length=200, description="SPA path to land on"),
    user: User | None = Depends(get_optional_current_user),
):
    """Return the provider URL that starts the round-trip.

    When the caller is signed in the provider identity is *linked* to that
    account instead of being used to sign in — that is how a user who signed up
    with Google connects GitHub for the repository import.
    """
    _require_provider(provider)

    state = security.create_oauth_state(
        provider,
        link_user_id=str(user.id) if user else None,
        next_path=_safe_next_path(next),
    )
    return {
        "authorization_url": oauth_service.build_authorization_url(
            oauth_service.get_provider(provider), state
        )
    }


@router.get("/oauth/mock/consent", response_class=HTMLResponse, include_in_schema=False)
async def mock_consent(state: str = Query(...)):
    """Stand-in for a provider's consent screen — development only.

    Served by this API so the whole round-trip (authorize → consent → callback)
    stays local. `_require_provider` keeps it a 503 unless `DEV_OAUTH_MOCK` is on.
    """
    _require_provider("mock")
    approve = oauth_service.callback_url(
        "mock", code=oauth_service.MOCK_CODE, state=state
    )
    deny = oauth_service.callback_url("mock", error="access_denied", state=state)
    return HTMLResponse(
        _MOCK_CONSENT_PAGE.replace(
            "__APPROVE__", html.escape(approve, quote=True)
        )
        .replace("__DENY__", html.escape(deny, quote=True))
        .replace("__EMAIL__", html.escape(oauth_service.MOCK_IDENTITY.email))
    )


@router.get("/oauth/{provider}/callback")
async def callback(
    provider: str,
    state: str = Query(...),
    code: str | None = Query(None),
    error: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Complete the round-trip and send the browser back to the SPA.

    Failures are redirected too, as `#error=<code>`: this endpoint is reached by
    a top-level browser navigation, so a JSON error would be a dead end.
    """
    _require_provider(provider)

    try:
        claims = security.read_oauth_state(state)
    except JWTError:
        return _frontend_redirect(error=ERROR_STATE)
    if claims.get("provider") != provider:
        return _frontend_redirect(error=ERROR_STATE)

    # A provider that reports a refusal (the user cancelled) sends `error` and
    # no `code` — that is a normal outcome, not a server failure.
    if error:
        return _frontend_redirect(error=ERROR_DENIED)
    if not code:
        return _frontend_redirect(error=ERROR_PROVIDER)

    provider_config = oauth_service.get_provider(provider)
    try:
        token = await oauth_service.exchange_code(provider_config, code)
        identity = await oauth_service.fetch_identity(provider_config, token["access_token"])
    except OAuthError:
        return _frontend_redirect(error=ERROR_PROVIDER)

    try:
        user = await _resolve_user(db, provider, identity, claims.get("link_user_id"))
    except LinkConflict:
        return _frontend_redirect(error=ERROR_LINK)

    await _store_account(db, user, provider, identity, token)
    await db.commit()

    access_token = security.create_access_token({"sub": user.email})
    return _frontend_redirect(token=access_token, next_path=claims.get("next"))


# --- internals ---------------------------------------------------------------


def _require_provider(provider: str) -> None:
    """404 for an unknown name, 503 for one this server cannot offer."""
    if provider not in oauth_service.PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown provider: {provider}"
        )
    if not oauth_service.is_configured(provider):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{provider} sign-in is not configured on this server",
        )


def _safe_next_path(next_path: str | None) -> str | None:
    """Accept only a same-site absolute path, never an absolute URL."""
    if next_path and next_path.startswith("/") and not next_path.startswith("//"):
        return next_path
    return None


def _frontend_redirect(token: str | None = None, next_path: str | None = None, error: str | None = None) -> RedirectResponse:
    fragment: dict[str, str] = {}
    if token:
        fragment["token"] = token
    if next_path:
        fragment["next"] = next_path
    if error:
        fragment["error"] = error
    return RedirectResponse(
        f"{settings.FRONTEND_URL}/auth/callback#{urlencode(fragment)}",
        status_code=status.HTTP_302_FOUND,
    )


async def _resolve_user(
    db: AsyncSession, provider: str, identity: Identity, link_user_id: str | None
) -> User:
    """Find (or create) the local account behind a provider identity."""
    account = await oauth_service.find_account_by_identity(
        db, provider, identity.provider_user_id
    )

    if link_user_id:
        # Explicit link request: the signed-in user is the intended owner.
        try:
            target = await db.get(User, uuid.UUID(link_user_id))
        except ValueError:
            target = None
        if target is None:
            raise LinkConflict("The account to link no longer exists")
        if account is not None and account.user_id != target.id:
            raise LinkConflict("That provider account is already linked to another user")
        return target

    if account is not None:
        owner = await db.get(User, account.user_id)
        if owner is not None:
            return owner

    # A verified provider email that already has a local account links the two
    # instead of colliding on the unique email constraint.
    existing = await db.execute(select(User).where(User.email == identity.email))
    user = existing.scalar_one_or_none()
    if user is not None:
        return user

    user = User(email=identity.email, password_hash=security.UNUSABLE_PASSWORD)
    db.add(user)
    # Flush so the row gets its id before the OAuthAccount points at it.
    await db.flush()
    return user


async def _store_account(
    db: AsyncSession, user: User, provider: str, identity: Identity, token: dict
) -> None:
    """Insert or refresh the provider row, including its access token."""
    account = await oauth_service.find_account_by_identity(
        db, provider, identity.provider_user_id
    )
    if account is None:
        account = OAuthAccount(
            user_id=user.id,
            provider=provider,
            provider_user_id=identity.provider_user_id,
        )
        db.add(account)

    account.user_id = user.id
    account.email = identity.email
    account.provider_login = identity.login
    account.access_token = token.get("access_token")
    account.scope = token.get("scope")
