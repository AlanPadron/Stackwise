"""Structured logging for analysis operations.

One line per event, JSON-ish payload, correlation id = analysis run id. Callers
pass field values; they are redacted and bounded here so a log line can never
carry a provider token or a database URL (and source contents are never logged
at all — only counts and paths).

Log levels follow the failure taxonomy: a degraded analyzer is a warning, a
failed run is an error, anything unexpected is logged with a traceback that is
still redacted.
"""

import json
import logging
from typing import Any

from app.analysis.redact import redact

logger = logging.getLogger("stackwise.analysis")

_MAX_FIELD_CHARS = 300


def log_event(event: str, *, level: int = logging.INFO, **fields: Any) -> None:
    """Emit one structured log line."""
    logger.log(level, "%s %s", event, json.dumps(_clean(fields), sort_keys=True))


def log_exception(event: str, exc: BaseException, **fields: Any) -> None:
    """Log an unexpected failure with its type and a redacted message."""
    payload = {"error_type": type(exc).__name__, "error": redact(str(exc), limit=_MAX_FIELD_CHARS)}
    payload.update(fields)
    logger.exception("%s %s", event, json.dumps(_clean(payload), sort_keys=True))


def _clean(fields: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, (int, float, bool)):
            cleaned[key] = value
        elif isinstance(value, (list, tuple, set)):
            cleaned[key] = [redact(item, limit=_MAX_FIELD_CHARS) for item in list(value)[:20]]
        else:
            cleaned[key] = redact(value, limit=_MAX_FIELD_CHARS)
    return cleaned
