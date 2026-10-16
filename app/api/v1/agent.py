"""The findings agent: can it run, and one chat turn.

Both endpoints require a session — the agent reads the caller's own findings —
and the chat endpoint is rate limited per user, because one request can occupy
the server's CPU for as long as the model takes to answer.

When the model is not installed the chat answers **503 with the reason**, never a
generated explanation: the SPA shows the install hint instead of pretending an
answer came from the model.
"""

import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.backend import AgentBackend, AgentUnavailable, ChatMessage
from app.agent.registry import resolve_backend
from app.agent.service import AgentService
from app.analysis.redact import redact
from app.api.deps import get_current_user
from app.core.config import settings
from app.core.ratelimit import agent_chat_limiter
from app.db.session import get_db
from app.models.user import User

router = APIRouter()


class AgentStatus(BaseModel):
    available: bool
    backend: str
    model: str
    #: Sanitised reason when `available` is false (no paths, no secrets).
    reason: Optional[str] = None
    max_context_findings: int
    #: What the composer may send: the server rejects anything longer.
    max_message_chars: int


class AgentTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=settings.AGENT_MAX_MESSAGE_CHARS)


class AgentChatRequest(BaseModel):
    """The conversation so far, plus the analysis it should be grounded in.

    `project_id` / `analysis_run_id` are optional: without them the agent has no
    findings to quote and says so, which is the honest answer for a question
    asked from a screen that is not about one analysis.
    """

    messages: list[AgentTurn]
    project_id: Optional[uuid.UUID] = None
    analysis_run_id: Optional[uuid.UUID] = None


class AgentChatResponse(BaseModel):
    reply: str
    backend: str
    model: str
    findings_used: int
    truncated: bool
    analysis_run_id: Optional[uuid.UUID] = None


def agent_backend() -> AgentBackend:
    """The configured backend, as a dependency so tests can substitute one."""
    return resolve_backend()


@router.get("/status", response_model=AgentStatus)
async def agent_status(
    user: User = Depends(get_current_user),
    backend: AgentBackend = Depends(agent_backend),
):
    """Whether the chat can answer, and what it is configured to run."""
    reason = backend.unavailable_reason()
    return AgentStatus(
        available=reason is None,
        backend=backend.name,
        model=backend.model,
        reason=reason,
        max_context_findings=settings.AGENT_MAX_CONTEXT_FINDINGS,
        max_message_chars=settings.AGENT_MAX_MESSAGE_CHARS,
    )


@router.post(
    "/chat",
    response_model=AgentChatResponse,
    responses={503: {"description": "The configured agent backend cannot run (see GET /agent/status)"}},
)
async def agent_chat(
    payload: AgentChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    backend: AgentBackend = Depends(agent_backend),
):
    """Answer the last message with the findings in scope as context."""
    turns = _validate_turns(payload.messages)
    enforce_agent_rate_limit(user)

    service = AgentService(db)
    try:
        answer = await service.reply(
            user=user,
            messages=turns,
            backend=backend,
            project_id=payload.project_id,
            analysis_run_id=payload.analysis_run_id,
        )
    except AgentUnavailable as exc:
        # The reason names a setting or a missing package, never a value.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=redact(str(exc), limit=300),
        ) from None

    return AgentChatResponse(
        reply=answer.reply,
        backend=answer.backend,
        model=answer.model,
        findings_used=answer.findings_used,
        truncated=answer.truncated,
        analysis_run_id=answer.analysis_run_id,
    )


# --- helpers -----------------------------------------------------------------


def enforce_agent_rate_limit(user: User) -> None:
    allowed, retry_after = agent_chat_limiter().check(str(user.id))
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many agent requests; slow down",
            headers={"Retry-After": str(max(1, int(retry_after) + 1))},
        )


def _validate_turns(messages: list[AgentTurn]) -> list[ChatMessage]:
    """The conversation as the model will see it, or a 422.

    Length is already bounded by the field, so this only rejects shapes the
    prompt builder cannot use: an empty conversation, more turns than the
    configured window, or a conversation that does not end with the user.
    """
    if not messages:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one message is required",
        )
    if len(messages) > settings.AGENT_MAX_MESSAGES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Conversation is too long",
        )
    if messages[-1].role != "user":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The last message must come from the user",
        )
    if not any(message.content.strip() for message in messages if message.role == "user"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Message must not be empty",
        )
    return [
        ChatMessage(role=message.role, content=message.content) for message in messages
    ]
