"""The seam between the API and whatever actually runs the agent.

Deliberately small. `AgentBackend` is all the rest of the feature knows, so a
hosted endpoint, a different checkpoint or a quantised runtime is a new
implementation *here* — `app/api/v1/agent.py`, the prompt builder and the SPA
stay untouched.
"""

from dataclasses import dataclass
from typing import AsyncIterator, Optional, Protocol, Sequence, runtime_checkable


@dataclass(frozen=True)
class ChatMessage:
    """One turn handed to the model: `system`, `user` or `assistant`."""

    role: str
    content: str


class AgentUnavailable(Exception):
    """The configured backend cannot run: dependencies or weights are missing.

    Carries a short, sanitised reason (no file paths, no environment values) that
    operators may read, and is what the API turns into a 503.
    """


@runtime_checkable
class AgentBackend(Protocol):
    """What the agent service needs from a runtime."""

    #: Stable identifier, reported by the API and used in logs.
    name: str
    #: The checkpoint this backend runs (the model id, not its filesystem path).
    model: str

    def unavailable_reason(self) -> Optional[str]:
        """`None` when `complete()` can run, otherwise why it cannot."""

    async def complete(
        self, messages: Sequence[ChatMessage], *, max_new_tokens: int
    ) -> str:
        """Answer the conversation, or raise `AgentUnavailable`."""


@runtime_checkable
class StreamingAgentBackend(Protocol):
    """An `AgentBackend` that can also hand the answer back as it is produced.

    Optional on purpose: streamed text is what makes "the model is writing" a
    real state rather than an animation, but a runtime that only speaks
    request/response should not have to fake it. `stream_answer()` below is what
    callers use, so they never branch on which kind of backend they hold.
    """

    def stream(
        self, messages: Sequence[ChatMessage], *, max_new_tokens: int
    ) -> AsyncIterator[str]:
        """Yield the answer in fragments, or raise `AgentUnavailable`."""


async def stream_answer(
    backend: AgentBackend,
    messages: Sequence[ChatMessage],
    *,
    max_new_tokens: int,
) -> AsyncIterator[str]:
    """One answer as a sequence of fragments, from whichever path exists.

    A backend with `stream()` streams it. One without yields its whole answer as
    a single fragment, because that is all a request/response runtime can
    honestly report — the caller still gets a sequence, and still gets it before
    the request ends.
    """
    stream = getattr(backend, "stream", None)
    if stream is None:
        yield await backend.complete(messages, max_new_tokens=max_new_tokens)
        return
    async for delta in stream(messages, max_new_tokens=max_new_tokens):
        yield delta


@dataclass(frozen=True)
class UnavailableBackend:
    """A backend the settings selected but that cannot produce text.

    It exists so the *configuration* stays readable — `status` still reports the
    backend and model the operator asked for — while every attempt to generate
    fails loudly instead of degrading into a made-up answer.
    """

    name: str
    model: str
    reason: str

    def unavailable_reason(self) -> Optional[str]:
        return self.reason

    async def complete(
        self, messages: Sequence[ChatMessage], *, max_new_tokens: int
    ) -> str:
        raise AgentUnavailable(self.reason)
