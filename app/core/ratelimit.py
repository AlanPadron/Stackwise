"""A tiny process-local sliding-window rate limiter.

Honest scope: this state lives in one Python process, so it bounds abuse per
worker, not per deployment. A serverless/multi-worker deployment needs the limit
enforced at the edge (Netlify/Vercel/ingress) or in a shared store — see
docs/ANALYSIS_ENGINE.md → Execution model. It is still worth having: it stops a
single client from queueing unbounded analysis work against one worker.
"""

import threading
import time
from collections import deque
from typing import Callable, Deque, Dict, Optional


class SlidingWindowRateLimiter:
    """`limit` events per `window_seconds` for each key."""

    def __init__(self, limit: int, window_seconds: float = 60.0, clock: Callable[[], float] = time.monotonic):
        self.limit = max(1, limit)
        self.window_seconds = window_seconds
        self._clock = clock
        self._events: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, float]:
        """Record an attempt. Returns `(allowed, retry_after_seconds)`.

        `retry_after_seconds` is 0 when the attempt is allowed, otherwise the
        time until the oldest event leaves the window.
        """
        now = self._clock()
        cutoff = now - self.window_seconds
        with self._lock:
            events = self._events.setdefault(key, deque())
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= self.limit:
                return False, max(0.0, events[0] + self.window_seconds - now)
            events.append(now)
            # Opportunistic cleanup: an unbounded dict keyed by user id is a slow
            # leak in a long-lived process.
            if len(self._events) > 10_000:
                for stale in [k for k, v in self._events.items() if not v]:
                    del self._events[stale]
            return True, 0.0

    def reset(self, key: str | None = None) -> None:
        """Drop recorded events (tests and admin tooling)."""
        with self._lock:
            if key is None:
                self._events.clear()
            else:
                self._events.pop(key, None)


_limiter: Optional[SlidingWindowRateLimiter] = None
_limiter_limit: Optional[int] = None


def analysis_start_limiter() -> SlidingWindowRateLimiter:
    """The limiter guarding analysis-start endpoints.

    Rebuilt when the configured limit changes, so tests and config reloads are
    not stuck with the value captured at import time.
    """
    global _limiter, _limiter_limit
    from app.core.config import settings

    limit = settings.ANALYSIS_RATE_LIMIT_PER_MINUTE
    if _limiter is None or _limiter_limit != limit:
        _limiter = SlidingWindowRateLimiter(limit)
        _limiter_limit = limit
    return _limiter


def reset_analysis_start_limiter() -> None:
    """Forget the cached limiter (tests)."""
    global _limiter, _limiter_limit
    if _limiter is not None:
        _limiter.reset()
    _limiter = None
    _limiter_limit = None


_agent_limiter: Optional[SlidingWindowRateLimiter] = None
_agent_limiter_limit: Optional[int] = None


def agent_chat_limiter() -> SlidingWindowRateLimiter:
    """The limiter guarding the findings-agent chat.

    Same reasoning as `analysis_start_limiter`: one request can hold the worker's
    CPU for the whole generation, so one client must not be able to queue an
    unbounded number of them.
    """
    global _agent_limiter, _agent_limiter_limit
    from app.core.config import settings

    limit = settings.AGENT_RATE_LIMIT_PER_MINUTE
    if _agent_limiter is None or _agent_limiter_limit != limit:
        _agent_limiter = SlidingWindowRateLimiter(limit)
        _agent_limiter_limit = limit
    return _agent_limiter


def reset_agent_chat_limiter() -> None:
    """Forget the cached limiter (tests)."""
    global _agent_limiter, _agent_limiter_limit
    if _agent_limiter is not None:
        _agent_limiter.reset()
    _agent_limiter = None
    _agent_limiter_limit = None
