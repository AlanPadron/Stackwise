"""Redaction of secrets and bounds on what we persist/log.

Repository content is user data, but *our* environment is not: database URLs,
provider tokens and application secrets must never reach an `AnalysisRun.error_message`,
a log line, or a finding's metadata. Everything that leaves the engine as text
goes through `redact()`.
"""

import json
import re
from typing import Any, Iterable, Optional

_REDACTION = "<redacted>"

#: Below this, a "secret" is too short to scrub safely: replacing it would cut
#: arbitrary words out of a message, and nothing that short is a credential.
MIN_SECRET_LENGTH = 8

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # our own database URLs (with or without credentials)
    (re.compile(r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|sqlite(?:\+aiosqlite)?)://\S+", re.I), _REDACTION),
    # credentials embedded in a URL
    (re.compile(r"\bhttps?://[^/\s:@]+:[^/\s@]+@", re.I), f"https://{_REDACTION}@"),
    # key/value pairs that name a secret
    (
        re.compile(
            r"(?i)\b(password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|"
            r"client[_-]?secret|authorization|bearer)\b\s*[:=]\s*(\"[^\"]*\"|'[^']*'|[^\s,;]{1,200})"
        ),
        lambda m: f"{m.group(1)}={_REDACTION}",
    ),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}\b"), _REDACTION),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"), _REDACTION),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"), _REDACTION),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), _REDACTION),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"), _REDACTION),
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}\b"), _REDACTION),
)


def redact(value: Any, *, limit: int = 2000) -> str:
    """Return `value` as a bounded string with secret-shaped substrings removed."""
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    text = text.replace("\x00", "")
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


def redact_with_values(
    value: Any, values: Iterable[Optional[str]], *, limit: int = 2000
) -> str:
    """`redact()`, plus a verbatim scrub of secrets given by their holder.

    Not every credential has a recognisable shape: a Cloudflare API token is 40
    unremarkable characters, so no pattern can find it. The one place that *can*
    remove it is whatever read the value in the first place, which is why this
    takes them as an argument instead of guessing.

    Short values are ignored: a two-character "secret" would redact half the
    message, and anything that short is not a credential worth holding.
    """
    text = "" if value is None else (value if isinstance(value, str) else str(value))
    for secret in values:
        if secret and len(secret) >= MIN_SECRET_LENGTH:
            text = text.replace(secret, _REDACTION)
    return redact(text, limit=limit)


def is_jsonable(value: Any, *, depth: int = 6) -> bool:
    """Whether `value` survives a JSON round-trip (and cannot smuggle objects in)."""
    if depth <= 0:
        return False
    if value is None or isinstance(value, (bool, int, float, str)):
        return True
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and is_jsonable(item, depth=depth - 1)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return all(is_jsonable(item, depth=depth - 1) for item in value)
    return False


def sanitize_json(value: Any, *, max_bytes: int = 4000, depth: int = 6) -> Optional[Any]:
    """Drop unsafe keys/values, redact strings and bound the serialised size.

    Returns `None` when nothing usable is left, so callers can leave the column
    NULL rather than storing `{}`.
    """
    cleaned = _sanitize(value, depth=depth)
    if cleaned is None or cleaned == {} or cleaned == []:
        return None
    encoded = json.dumps(cleaned, sort_keys=True, default=str)
    if len(encoded) <= max_bytes:
        return cleaned

    # Keep what fits: truncate lists, then strings.
    if isinstance(cleaned, dict):
        trimmed: dict[str, Any] = {}
        for key in sorted(cleaned):
            candidate = dict(trimmed)
            candidate[key] = cleaned[key]
            if len(json.dumps(candidate, sort_keys=True, default=str)) > max_bytes:
                break
            trimmed = candidate
        return trimmed or None
    return None


def _sanitize(value: Any, *, depth: int) -> Optional[Any]:
    if depth <= 0:
        return None
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return redact(value, limit=512) or None
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key or len(key) > 64:
                continue
            sanitized = _sanitize(item, depth=depth - 1)
            if sanitized is not None:
                out[key] = sanitized
        return out or None
    if isinstance(value, (list, tuple)):
        items = [_sanitize(item, depth=depth - 1) for item in value[:50]]
        items = [item for item in items if item is not None]
        return items or None
    return None


def redact_url(value: Any, *, limit: int = 512) -> Optional[str]:
    """Keep only http(s) references; anything else is dropped, not stored."""
    text = redact(value, limit=limit).strip()
    if not text.lower().startswith(("http://", "https://")):
        return None
    return text
