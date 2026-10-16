"""Create (or reset) a local test account.

There is no administrator role in Stackwise: `users` holds an email and a bcrypt
hash, and every account reaches exactly its own data (`app/api/deps.py`). This
script therefore creates an **ordinary** account — which is all a debug session
needs — and it deliberately holds no credential of its own.

It used to: until 1.5.0 this file shipped with a hardcoded
`admin@stackwise.com` / `1234` pair, i.e. a permanent login that anyone reading
the repository (or the deployed image) could use. It is now supplied by whoever
runs the script, is never echoed, and is never stored in clear text.

Usage:

    python create_admin.py test@example.test                  # prompts for the password
    python create_admin.py test@example.test --reset          # replace an existing password
    python create_admin.py test@example.test --password '…'   # non-interactive (CI); note
                                                              # that this lands in shell history

The account is created in whatever database `SQLALCHEMY_URL` points at, so run it
against a development database — the target is printed before anything is
written. Passwords must be at least 8 characters, the same rule the API applies
to `POST /auth/register`; the account cannot log in with anything else.
"""

import argparse
import asyncio
import getpass
import os
import re
import sys

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import select

from app.core.security import get_password_hash
from app.db.session import AsyncSessionLocal
from app.models.user import User

#: The API's own rule (`app/schemas/user.py`), applied here so a script-created
#: account is never weaker than one created through the endpoint.
MIN_PASSWORD_LENGTH = 8


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create or reset a Stackwise test account.",
    )
    parser.add_argument("email", help="login address of the account")
    parser.add_argument(
        "--password",
        help="password for the account; prompted for (hidden) when omitted",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="replace the password of an account that already exists",
    )
    return parser.parse_args(argv)


def target_database() -> str:
    """Where this would write, with any credentials removed."""
    url = os.environ.get("SQLALCHEMY_URL") or "sqlite+aiosqlite:///./stackwise.db"
    match = re.match(r"([a-z+]+)://(?:[^:/@]+(?::[^@]*)?@)?(.*)", url)
    if not match:
        return "(unrecognised)"
    scheme, rest = match.groups()
    return f"{scheme}://{rest}" if rest else f"{scheme}://(local)"


def normalise_email(raw: str) -> str:
    """The address the API would accept, or a refusal explaining why not."""
    try:
        return validate_email(raw, check_deliverability=False).normalized
    except EmailNotValidError as exc:
        raise SystemExit(f"Invalid email address: {exc}") from None


def ask_password() -> str:
    password = getpass.getpass("Password (input hidden): ")
    if password != getpass.getpass("Repeat password: "):
        raise SystemExit("The two passwords differ; nothing was written.")
    return password


async def create_account(email: str, password: str, *, reset: bool) -> None:
    async with AsyncSessionLocal() as session:
        existing = (
            await session.execute(select(User).where(User.email == email))
        ).scalar_one_or_none()

        if existing and not reset:
            raise SystemExit(
                f"{email} already exists (id {existing.id}); "
                "pass --reset to replace its password."
            )

        if existing:
            existing.password_hash = get_password_hash(password)
            action = "password replaced"
        else:
            session.add(User(email=email, password_hash=get_password_hash(password)))
            action = "account created"

        await session.commit()

    print(f"{action}: {email}")
    print("Sign in at the SPA with that address and the password you just typed.")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    password = args.password or ask_password()
    if len(password) < MIN_PASSWORD_LENGTH:
        raise SystemExit(
            f"The password must be at least {MIN_PASSWORD_LENGTH} characters; "
            "nothing was written."
        )

    email = normalise_email(args.email)
    print(f"Database: {target_database()}")
    asyncio.run(create_account(email, password, reset=args.reset))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
