"""The seam between the API and whatever actually runs the agent.

Deliberately small. `AgentBackend` is all the rest of the feature knows, so a
hosted endpoint, a different checkpoint or a quantised runtime is a new
implementation *here* — `app/api/v1/agent.py`, the prompt builder and the SPA
stay untouched.
"""

from dataclasses import dataclass
from typing import Optional, Protocol, Sequence, runtime_checkable


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
