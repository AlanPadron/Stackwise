"""Password hashing, the password policy, and JWT issuing/decoding.

Passwords use bcrypt directly (not passlib): `_bcrypt_bytes` exists because
bcrypt only reads the first 72 bytes and raises on longer input.
"""

import base64
import hashlib
import secrets
from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings

ALGORITHM = "HS256"

# Subject of the short-lived token that carries the OAuth `state` parameter, so
# a state can never be mistaken for a session token (and vice versa).
OAUTH_STATE_SUBJECT = "oauth-state"

# Name of the short-lived cookie that carries a provider round-trip's PKCE
# verifier (see `new_code_verifier`). HttpOnly: the SPA never needs to read it.
OAUTH_PKCE_COOKIE = "sw_oauth_pkce"

# Stored in `users.password_hash` for accounts that only ever sign in through an
# OAuth provider. It is deliberately not a bcrypt hash, so `verify_password`
# rejects it and the account stays unusable through the password endpoint.
UNUSABLE_PASSWORD = "!oauth"

# --- password policy ---------------------------------------------------------
# What a password has to satisfy before it is hashed. It lives here, next to the
# hashing, and `app/schemas/user.py` is the single caller — registration today,
# a password change tomorrow, both through the same rule set.
PASSWORD_MIN_LENGTH = 10
# In bytes, not characters: bcrypt reads the first 72 bytes, so a longer
# password would be silently truncated rather than refused.
PASSWORD_MAX_BYTES = 72

# Bases that make an otherwise-compliant password worthless. Deliberately short
# — it is a floor, not a substitute for the length rule — and compared with the
# separators and trailing digits stripped, so `P@ssword-2024!` is caught too.
COMMON_PASSWORD_BASES = frozenset(
    {
        "password", "passwd", "passw0rd", "qwerty", "qwertyuiop", "azerty",
        "letmein", "welcome", "admin", "administrator", "root", "iloveyou",
        "monkey", "dragon", "sunshine", "princess", "football", "baseball",
        "superman", "master", "shadow", "trustno1", "changeme", "secret",
        "stackwise", "contraseña", "contrasena",
    }
)


def _password_base(password: str) -> str:
    """The comparable core of a password: letters and digits, lowercase."""
    alphanumeric = "".join(ch for ch in password.lower() if ch.isalnum())
    return alphanumeric.rstrip("0123456789")


def password_problem(password: str) -> Optional[str]:
    """Why this password is unacceptable, or `None` when it passes.

    The message is English and operator-facing, like every other API detail; the
    SPA owns the translated wording of its own (mirrored) client-side check.
    """
    if len(password) < PASSWORD_MIN_LENGTH:
        return f"Password must be at least {PASSWORD_MIN_LENGTH} characters"
    if len(password.encode("utf-8")) > PASSWORD_MAX_BYTES:
        return f"Password must be at most {PASSWORD_MAX_BYTES} bytes"
    if not any(ch.isalpha() for ch in password) or not any(ch.isdigit() for ch in password):
        return "Password must mix letters and digits"
    if _password_base(password) in COMMON_PASSWORD_BASES:
        return "Password is too common"
    return None


def normalize_email(email: str) -> str:
    """The canonical form of an address, used for storage and for every lookup.

    `EmailStr` already normalises the domain; the local part is technically
    case-sensitive, but no provider treats it that way — and two accounts that
    differ only in case are two accounts to an attacker and one to the person
    typing it, which is how account takeover by re-registration happens.
    """
    return email.strip().lower()


# A real bcrypt hash (cost 12, like `get_password_hash`) of a value nobody
# knows, so an unknown address costs the same as a wrong password. Without it the
# login endpoint answers instantly for an email that does not exist and slowly
# for one that does, which is an account-enumeration oracle.
DUMMY_PASSWORD_HASH = "$2b$12$KqlB7xTZPi68xyRGIJQ1Gu1xqw.s4.zGNBLrxCqscVUuDdX0olVnu"


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


def verify_against_dummy(password: str) -> None:
    """Spend one bcrypt verification when there is no account to check against.

    Same cost as a real check, which is the point: see `DUMMY_PASSWORD_HASH`.
    """
    verify_password(password, DUMMY_PASSWORD_HASH)

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


def create_oauth_state(
    provider: str,
    link_user_id: Optional[str],
    next_path: Optional[str],
    code_challenge: Optional[str] = None,
) -> str:
    """Sign the `state` round-tripped through an OAuth provider.

    Carries which provider started the flow, an optional user to link the new
    identity to (the "connect GitHub" path), where the SPA should land, and the
    PKCE challenge (RFC 7636) the callback checks the verifier against. The
    challenge is public by design — it is what the browser sends to the
    provider — so signing it is enough; the *verifier* never travels in a URL.
    """
    return create_access_token(
        {
            "sub": OAUTH_STATE_SUBJECT,
            "provider": provider,
            "link_user_id": link_user_id,
            "next": next_path,
            "code_challenge": code_challenge,
        },
        expires_delta=timedelta(minutes=settings.OAUTH_STATE_EXPIRE_MINUTES),
    )


def read_oauth_state(token: str) -> dict:
    """Decode a state token. Raises `JWTError` when it is invalid or expired."""
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    if payload.get("sub") != OAUTH_STATE_SUBJECT:
        raise JWTError("not an oauth state token")
    return payload


def new_code_verifier() -> str:
    """A PKCE `code_verifier`: 43–128 characters from the unreserved set."""
    return secrets.token_urlsafe(32)


def code_challenge(verifier: str) -> str:
    """The S256 challenge for a verifier: base64url(sha256(verifier)), unpadded."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
