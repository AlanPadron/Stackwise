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
