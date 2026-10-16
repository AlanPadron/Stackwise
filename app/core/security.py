"""Password hashing and JWT issuing/decoding.

Passwords use bcrypt directly (not passlib): `_bcrypt_bytes` exists because
bcrypt only reads the first 72 bytes and raises on longer input.
"""

from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings

ALGORITHM = "HS256"

# Subject of the short-lived token that carries the OAuth `state` parameter, so
# a state can never be mistaken for a session token (and vice versa).
OAUTH_STATE_SUBJECT = "oauth-state"

# Stored in `users.password_hash` for accounts that only ever sign in through an
# OAuth provider. It is deliberately not a bcrypt hash, so `verify_password`
# rejects it and the account stays unusable through the password endpoint.
UNUSABLE_PASSWORD = "!oauth"

# bcrypt only considers the first 72 bytes and raises on longer input.
def _bcrypt_bytes(password: str) -> bytes:
    return password.encode('utf-8')[:72]

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Constant-time-ish bcrypt check that also tolerates a non-bcrypt hash.

    The guard matters because OAuth-only accounts store `UNUSABLE_PASSWORD`
    instead of a hash: `bcrypt.checkpw` raises on malformed input.
    """
    if not hashed_password or not hashed_password.startswith("$2"):
        return False
    try:
        return bcrypt.checkpw(_bcrypt_bytes(plain_password), hashed_password.encode('utf-8'))
    except ValueError:
        return False

def get_password_hash(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(_bcrypt_bytes(password), salt).decode('utf-8')

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Sign a JWT. Callers pass `{"sub": <email>}` — that subject is what
    `app/api/deps.py::get_current_user` looks the account up by."""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_oauth_state(provider: str, link_user_id: Optional[str], next_path: Optional[str]) -> str:
    """Sign the `state` round-tripped through an OAuth provider.

    Carries which provider started the flow, an optional user to link the new
    identity to (the "connect GitHub" path) and where the SPA should land.
    """
    return create_access_token(
        {
            "sub": OAUTH_STATE_SUBJECT,
            "provider": provider,
            "link_user_id": link_user_id,
            "next": next_path,
        },
        expires_delta=timedelta(minutes=settings.OAUTH_STATE_EXPIRE_MINUTES),
    )


def read_oauth_state(token: str) -> dict:
    """Decode a state token. Raises `JWTError` when it is invalid or expired."""
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    if payload.get("sub") != OAUTH_STATE_SUBJECT:
        raise JWTError("not an oauth state token")
    return payload
