"""Request and response shapes of the OAuth sign-in endpoints."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ProviderAvailability(BaseModel):
    """Which OAuth providers this server can offer.

    `mock` is the development-only stand-in (`DEV_OAUTH_MOCK`); it is `False` on
    any normal deployment.
    """

    google: bool
    github: bool
    mock: bool


class AuthorizeResponse(BaseModel):
    """Where the SPA should send the browser to start the provider round-trip."""

    authorization_url: str


class LinkedAccount(BaseModel):
    """One provider identity attached to the signed-in account.

    The provider's access token is deliberately absent: it is used by the API
    (repository imports) and never handed to the browser.
    """

    provider: str
    login: Optional[str] = None
    email: Optional[str] = None
    created_at: Optional[datetime] = None
