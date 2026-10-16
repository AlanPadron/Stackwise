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
import logging
import uuid
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_optional_current_user
from app.core import security
from app.core.config import settings
from app.db.session import get_db
from app.models.oauth import OAuthAccount
from app.models.user import User
from app.schemas.oauth import AuthorizeResponse, LinkedAccount, ProviderAvailability
from app.services import oauth as oauth_service
from app.services.oauth import Identity, LinkConflict, OAuthError

router = APIRouter()

# Error codes handed back to the SPA, which owns the (translated) wording.
ERROR_STATE = "state"
ERROR_PROVIDER = "provider"
ERROR_LINK = "link"
ERROR_DENIED = "denied"
ERROR_PKCE = "pkce"
ERROR_LAST_LOGIN = "last_login"

# What a provider row is allowed to disclose back to the SPA: no access token,
# no scope, nothing the browser could use to call the provider itself.
_LINKED_FIELDS = ("provider", "provider_login", "email", "created_at")

logger = logging.getLogger("stackwise")


def _linked(account: OAuthAccount) -> LinkedAccount:
    """The public face of a provider row (see `_LINKED_FIELDS`)."""
    return LinkedAccount(
        provider=account.provider,
        login=account.provider_login,
        email=account.email,
        created_at=account.created_at,
    )

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


@router.get("/oauth/links", response_model=list[LinkedAccount])
async def list_links(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Which provider identities are attached to the caller's account.

    Answers with the provider's own account name (GitHub's login, the address the
    provider reported) and nothing else: no access token, no scope, nothing the
    browser could use to call the provider on its own.
    """
    accounts = await oauth_service.linked_accounts(db, user.id)
    return [_linked(account) for account in accounts]


@router.delete("/oauth/links/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink(
    provider: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Detach one provider identity from the caller's account.

    Refused (409) when that identity is the account's only way in: an account
    created through a provider carries no password, so removing its last link
    would lock the owner out of their own data with no way back in.
    """
    if provider not in oauth_service.PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown provider: {provider}"
        )

    account = await oauth_service.find_account_for_user(db, user.id, provider)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"{provider} is not connected"
        )

    if user.password_hash == security.UNUSABLE_PASSWORD:
        linked = await oauth_service.linked_accounts(db, user.id)
        if len(linked) <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "This is the only way to sign in to this account; "
                    "connect another provider first"
                ),
            )

    # Best effort at the provider, then forget it locally either way: a token we
    # can no longer use should not stay live over there.
    try:
        await oauth_service.revoke_token(
            oauth_service.get_provider(provider), account.access_token
        )
    except OAuthError:
        logger.warning("Could not revoke the %s token while unlinking", provider, exc_info=True)

    await db.delete(account)
    await db.commit()


@router.get("/oauth/{provider}/authorize", response_model=AuthorizeResponse)
async def authorize(
    provider: str,
    response: Response,
    next: str | None = Query(None, max_length=200, description="SPA path to land on"),
    user: User | None = Depends(get_optional_current_user),
):
    """Return the provider URL that starts the round-trip.

    When the caller is signed in the provider identity is *linked* to that
    account instead of being used to sign in — that is how a user who signed up
    with Google connects GitHub for the repository import.
    """
    _require_provider(provider)

    # PKCE: the verifier goes into an HttpOnly cookie bound to this browser, the
    # challenge into the authorize URL, and the callback refuses to spend a code
    # unless the two agree. Same host as the callback (cookies ignore the port),
    # so the dev proxy on :3000 and the API on :8001 share it.
    verifier = security.new_code_verifier()
    challenge = security.code_challenge(verifier)
    response.set_cookie(
        security.OAUTH_PKCE_COOKIE,
        verifier,
        max_age=settings.OAUTH_STATE_EXPIRE_MINUTES * 60,
        path=f"{settings.API_V1_STR}/auth/oauth",
        httponly=True,
        samesite="lax",
        secure=settings.API_PUBLIC_URL.startswith("https"),
    )

    state = security.create_oauth_state(
        provider,
        link_user_id=str(user.id) if user else None,
        next_path=_safe_next_path(next),
        code_challenge=challenge,
    )
    return {
        "authorization_url": oauth_service.build_authorization_url(
            oauth_service.get_provider(provider), state, challenge
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
    request: Request,
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

    # PKCE before anything is spent: the verifier must be the one this browser
    # was handed when the flow started, and it must hash to the challenge the
    # state carries. A code that leaked to another browser is worthless here.
    verifier = request.cookies.get(security.OAUTH_PKCE_COOKIE)
    challenge = claims.get("code_challenge")
    if not verifier or not challenge or security.code_challenge(verifier) != challenge:
        return _frontend_redirect(error=ERROR_PKCE)

    # A provider that reports a refusal (the user cancelled) sends `error` and
    # no `code` — that is a normal outcome, not a server failure.
    if error:
        return _frontend_redirect(error=ERROR_DENIED)
    if not code:
        return _frontend_redirect(error=ERROR_PROVIDER)

    provider_config = oauth_service.get_provider(provider)
    try:
        token = await oauth_service.exchange_code(provider_config, code, verifier)
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
