"""Authentication endpoints: register, login and the current-user probe.

Both unauthenticated endpoints are rate limited per client address, and login
additionally per account, so guessing a password costs something per minute
instead of being free. Everything else that a sign-up has to satisfy (the
password policy, the canonical casing of an email) lives in
`app.core.security` and is applied by the schemas, so a second way to create or
authenticate an account cannot drift from these two.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core import security
from app.core.ratelimit import auth_login_limiter, auth_register_limiter
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import Token, UserCreate, UserResponse

router = APIRouter()

# One message for both failure modes, so the endpoint cannot be used to find out
# whether an address has an account here.
_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Incorrect email or password",
    headers={"WWW-Authenticate": "Bearer"},
)


def _client_address(request: Request) -> str:
    """Who to count a limit against.

    `request.client` is the peer of *this* process: behind a reverse proxy that is
    the proxy, so a deployment that terminates TLS elsewhere must pass the real
    address through and be limited there (see the module docstring of
    `app.core.ratelimit`).
    """
    return request.client.host if request.client else "unknown"


def _rate_limited(retry_after: float, detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=detail,
        headers={"Retry-After": str(max(1, int(retry_after) + 1))},
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user_in: UserCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Create an account. Emails are unique, so duplicates are a 400.

    The password is validated and the address canonicalised by `UserCreate`
    before this runs, so a 422 here means the request never reached the database.
    """
    allowed, retry_after = auth_register_limiter().check(_client_address(request))
    if not allowed:
        raise _rate_limited(retry_after, "Too many sign-up attempts; try again later")

    existing = await db.execute(select(User).where(User.email == user_in.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    user = User(email=user_in.email, password_hash=security.get_password_hash(user_in.password))
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=Token)
async def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """OAuth2 password flow: form fields `username` (the email) and `password`.

    Both "unknown email" and "wrong password" return the same 401 so the
    endpoint cannot be used to enumerate accounts — including the time it takes
    to answer, which is why an unknown address still pays for a bcrypt check.
    """
    email = security.normalize_email(form_data.username)

    # Per address *and* per account, atomically: a shared address cannot be used
    # to lock out its neighbours, and one account cannot be sprayed from many
    # addresses.
    limiter = auth_login_limiter()
    allowed, retry_after = limiter.check_all(
        (f"account:{email}", f"address:{_client_address(request)}")
    )
    if not allowed:
        raise _rate_limited(retry_after, "Too many sign-in attempts; try again later")

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    if user is None:
        security.verify_against_dummy(form_data.password)
        raise _INVALID_CREDENTIALS

    if not security.verify_password(form_data.password, user.password_hash):
        raise _INVALID_CREDENTIALS

    return {"access_token": security.create_access_token({"sub": user.email}), "token_type": "bearer"}


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)):
    """Who the bearer token belongs to; the SPA calls this on every reload."""
    return user
