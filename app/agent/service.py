"""Scoping a request to the caller's own data, then one generation call.

Two platform rules carry over: a caller only ever reaches their own projects —
checked here, because these ids arrive in the request body rather than in the
path, so the path-parameter dependencies cannot be used — and everything that
reaches the model is bounded by settings.
"""

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import AsyncIterator, Optional, Sequence

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.backend import (
    AgentBackend,
    AgentUnavailable,
    ChatMessage,
    stream_answer,
)
from app.agent.prompt import FindingContext, build_digest, build_messages
from app.api.deps import get_owned_analysis_run, get_owned_project
from app.core.config import settings
from app.models.analysis import AnalysisRun, Finding
from app.models.project import Project
from app.models.user import User

# Findings are read in the same order the SPA lists them: severity first, then
# location, so a capped context keeps the most serious ones.
_SEVERITY_RANK = case(
    (Finding.severity == "critical", 0),
    (Finding.severity == "high", 1),
    (Finding.severity == "medium", 2),
    (Finding.severity == "low", 3),
    (Finding.severity == "info", 4),
    else_=5,
)
# A run that finished with degraded analyzers still produced findings.
_FINISHED_STATUSES = ("completed", "completed_with_errors")


@dataclass(frozen=True)
class AgentReply:
    """What the endpoint returns: the answer plus how it was produced."""

    reply: str
    backend: str
    model: str
    findings_used: int
    analysis_run_id: Optional[uuid.UUID]
    truncated: bool


@dataclass(frozen=True)
class AgentContext:
    """One answer's inputs, resolved before the model is asked anything.

    Built once so the whole-answer endpoint and the streamed one quote exactly
    the same findings to the same runtime: the scope, the digest and the system
    prompt are decided here and nowhere else.
    """

    #: The conversation as the model will see it, system turn included.
    conversation: list[ChatMessage]
    findings_used: int
    truncated: bool
    analysis_run_id: Optional[uuid.UUID]
    backend_name: str
    model: str


class AgentService:
    """One request's worth of work: scope → prompt → generation."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def reply(
        self,
        *,
        user: User,
        messages: Sequence[ChatMessage],
        backend: AgentBackend,
        project_id: Optional[uuid.UUID] = None,
        analysis_run_id: Optional[uuid.UUID] = None,
    ) -> AgentReply:
        """Explain the findings in scope, in the conversation's language.

        Raises `AgentUnavailable` when the model cannot run — before any work is
        done on the prompt, so an unconfigured agent costs nothing.
        """
        context = await self.prepare(
            user=user,
            messages=messages,
            backend=backend,
            project_id=project_id,
            analysis_run_id=analysis_run_id,
        )

        try:
            answer = await asyncio.wait_for(
                backend.complete(
                    context.conversation, max_new_tokens=settings.AGENT_MAX_NEW_TOKENS
                ),
                timeout=settings.AGENT_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            # `wait_for` stops waiting; a generation already running in a worker
            # thread cannot be cancelled and simply finishes unread.
            raise AgentUnavailable(
                f"the model did not answer within {int(settings.AGENT_TIMEOUT_SECONDS)} seconds"
            ) from None

        return AgentReply(
            reply=answer.strip(),
            backend=context.backend_name,
            model=context.model,
            findings_used=context.findings_used,
            analysis_run_id=context.analysis_run_id,
            truncated=context.truncated,
        )

    async def stream(
        self, *, context: AgentContext, backend: AgentBackend
    ) -> AsyncIterator[str]:
        """The same answer, as fragments, bounded by the same budget.

        The deadline is checked per fragment instead of wrapping the whole
        iteration in `wait_for`: the upstream connection already has its own read
        timeout for a model that goes quiet, while a deadline that also counted
        the client reading the response would be measuring the wrong thing.
        """
        deadline = time.monotonic() + settings.AGENT_TIMEOUT_SECONDS
        produced = 0

        async for delta in stream_answer(
            backend,
            context.conversation,
            max_new_tokens=settings.AGENT_MAX_NEW_TOKENS,
        ):
            if time.monotonic() > deadline:
                raise AgentUnavailable(
                    f"the model did not finish within {int(settings.AGENT_TIMEOUT_SECONDS)} seconds"
                )
            produced += len(delta.strip())
            yield delta

        if produced == 0:
            # An empty answer is a failure, not a blank reply: the transport may
            # already have sent a 200 and some frames, so this is the only place
            # left to say so.
            raise AgentUnavailable("the model returned no text")

    async def prepare(
        self,
        *,
        user: User,
        messages: Sequence[ChatMessage],
        backend: AgentBackend,
        project_id: Optional[uuid.UUID] = None,
        analysis_run_id: Optional[uuid.UUID] = None,
    ) -> AgentContext:
        """Resolve the scope and build the conversation the model will receive."""
        reason = backend.unavailable_reason()
        if reason is not None:
            raise AgentUnavailable(reason)

        project, run = await self._scope(
            user=user, project_id=project_id, analysis_run_id=analysis_run_id
        )
        findings, total = await self._findings(run)
        digest = build_digest(
            findings,
            max_findings=settings.AGENT_MAX_CONTEXT_FINDINGS,
            max_chars=settings.AGENT_MAX_CONTEXT_CHARS,
        )
        conversation = build_messages(
            history=messages,
            digest=digest,
            project_name=project.name if project is not None else None,
            run_label=_run_label(run),
            max_messages=settings.AGENT_MAX_MESSAGES,
            max_message_chars=settings.AGENT_MAX_MESSAGE_CHARS,
        )

        return AgentContext(
            conversation=conversation,
            findings_used=digest.used,
            truncated=digest.truncated,
            analysis_run_id=run.id if run is not None else None,
            backend_name=backend.name,
            model=backend.model,
        )

    # --- scope ------------------------------------------------------------

    async def _scope(
        self,
        *,
        user: User,
        project_id: Optional[uuid.UUID],
        analysis_run_id: Optional[uuid.UUID],
    ) -> tuple[Optional[Project], Optional[AnalysisRun]]:
        """The project/run the answer is about, reusing the ownership checks.

        `get_owned_project` / `get_owned_analysis_run` are plain coroutines with
        dependency defaults, so calling them with explicit arguments keeps the
        404-vs-403 behaviour identical to the rest of the API.
        """
        if analysis_run_id is not None:
            run = await get_owned_analysis_run(
                analysis_id=analysis_run_id, user=user, db=self._db
            )
            project = await get_owned_project(
                project_id=run.project_id, user=user, db=self._db
            )
            return project, run

        if project_id is not None:
            project = await get_owned_project(
                project_id=project_id, user=user, db=self._db
            )
            return project, await self._latest_run(project.id)

        return None, None

    async def _latest_run(self, project_id: uuid.UUID) -> Optional[AnalysisRun]:
        """The run worth explaining: the newest finished one, else the newest.

        Preferring a finished run means a chat opened while an analysis is still
        running explains the previous results instead of an empty list.
        """
        for statuses in (_FINISHED_STATUSES, None):
            query = select(AnalysisRun).where(AnalysisRun.project_id == project_id)
            if statuses is not None:
                query = query.where(AnalysisRun.status.in_(statuses))
            run = (
                await self._db.execute(
                    query.order_by(AnalysisRun.created_at.desc(), AnalysisRun.id).limit(1)
                )
            ).scalar_one_or_none()
            if run is not None:
                return run
        return None

    async def _findings(
        self, run: Optional[AnalysisRun]
    ) -> tuple[list[FindingContext], int]:
        """The capped, severity-ordered findings of one run plus their total."""
        if run is None:
            return [], 0

        total = (
            await self._db.execute(
                select(func.count(Finding.id)).where(Finding.analysis_run_id == run.id)
            )
        ).scalar() or 0
        rows = (
            (
                await self._db.execute(
                    select(Finding)
                    .where(Finding.analysis_run_id == run.id)
                    .order_by(_SEVERITY_RANK, Finding.file_path, Finding.line_start)
                    .limit(settings.AGENT_MAX_CONTEXT_FINDINGS)
                )
            )
            .scalars()
            .all()
        )
        return [
            FindingContext(
                severity=row.severity,
                category=row.category,
                tool=row.tool,
                rule_id=row.rule_id,
                title=row.title,
                message=row.message,
                file_path=row.file_path,
                line_start=row.line_start,
            )
            for row in rows
        ], total


def _run_label(run: Optional[AnalysisRun]) -> Optional[str]:
    """Human-readable identity of the run, without leaking anything else."""
    if run is None:
        return None
    origin = run.source_ref or run.source_type
    return f"{origin} ({run.status})"
