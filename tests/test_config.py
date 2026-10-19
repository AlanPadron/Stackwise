"""Settings that must be refused before the app can serve a request.

The signing key is the one value whose weakness is invisible at runtime: a short
or copy-pasted key signs perfectly valid tokens. These tests pin the refusal.
"""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def settings_with(secret: str) -> Settings:
    # `_env_file=None`: the test states its own value instead of borrowing the
    # developer's `.env` (process environment still supplies the other fields).
    return Settings(_env_file=None, SECRET_KEY=secret)


def test_a_short_secret_key_is_refused():
    with pytest.raises(ValidationError) as raised:
        settings_with("x" * 31)

    assert "at least 32 characters" in str(raised.value)


def test_the_env_example_placeholder_is_refused():
    with pytest.raises(ValidationError) as raised:
        settings_with("your-super-secret-key-change-me-in-production")

    assert "must not be the .env.example placeholder" in str(raised.value)


def test_a_32_character_secret_key_is_accepted():
    assert settings_with("x" * 32).SECRET_KEY == "x" * 32
