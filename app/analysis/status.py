"""Analysis run lifecycle: the allowed states and how a run moves between them.

    pending ──▶ running ──▶ completed
       │           │    └─▶ completed_with_errors   (some analyzer failed)
       │           └──────▶ failed
       └───────────────────▶ cancelled / failed     (never started)

A terminal state is terminal: a second pipeline execution for the same run is a
no-op (`AnalysisOrchestrator.execute` checks), and an invalid transition raises
instead of being written. Terminal states are only written together with the
results they describe — see `AnalysisPersistenceService.persist_results`, which
inserts findings and sets the status in one transaction.

`reap_stale_runs` is the recovery path promised by the spec: a run whose worker
died (process restart, deployment, hard kill) is still `pending`/`running` after
its budget expired, and is moved to `failed` with `error_category=stale_run` so
it cannot look busy forever.
"""

from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.errors import AnalysisError, ErrorCategory
from app.analysis.observability import log_event
from app.analysis.redact import redact
from app.core.config import settings


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Rows written before the engine existed used `processing`.
LEGACY_STATUS_ALIASES = {"processing": RunStatus.RUNNING}

TERMINAL_STATUSES = frozenset(
    {RunStatus.COMPLETED, RunStatus.COMPLETED_WITH_ERRORS, RunStatus.FAILED, RunStatus.CANCELLED}
)
ACTIVE_STATUSES = frozenset({RunStatus.PENDING, RunStatus.RUNNING})

ALLOWED_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.PENDING: frozenset({RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED}),
    RunStatus.RUNNING: frozenset(
        {RunStatus.COMPLETED, RunStatus.COMPLETED_WITH_ERRORS, RunStatus.FAILED, RunStatus.CANCELLED}
    ),
    RunStatus.COMPLETED: frozenset(),
    RunStatus.COMPLETED_WITH_ERRORS: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
}


class InvalidStatusTransition(AnalysisError):
    """A transition the lifecycle does not allow."""

    category = ErrorCategory.ORCHESTRATION


def normalize_status(value: Any) -> RunStatus:
    """Map a stored status (including the legacy `processing`) to `RunStatus`."""
    if isinstance(value, RunStatus):
        return value
    text = str(value or "").strip().lower()
    if text in LEGACY_STATUS_ALIASES:
        return LEGACY_STATUS_ALIASES[text]
    try:
        return RunStatus(text)
    except ValueError as exc:
        raise InvalidStatusTransition(f"unknown analysis status: {value!r}") from exc


class AnalysisStatusService:
    """Lifecycle transitions and stale-run recovery for one session."""

    def __init__(self, db: AsyncSession):
        self._db = db

    # --- transitions -------------------------------------------------------

    @staticmethod
    def can_transition(current: Any, target: RunStatus) -> bool:
        try:
            current_status = normalize_status(current)
        except InvalidStatusTransition:
            return False
        return target in ALLOWED_TRANSITIONS[current_status]

    @staticmethod
    def ensure_transition(current: Any, target: RunStatus) -> RunStatus:
        current_status = normalize_status(current)
        if target not in ALLOWED_TRANSITIONS[current_status]:
            raise InvalidStatusTransition(
                f"cannot move an analysis run from {current_status.value!r} to {target.value!r}"
            )
        return current_status

    async def mark_running(self, run) -> None:
        """`pending → running`, committed so pollers see progress immediately."""
        self.ensure_transition(run.status, RunStatus.RUNNING)
        run.status = RunStatus.RUNNING.value
        await self._db.commit()

    async def mark_terminal(
        self,
        run,
        status: RunStatus,
        *,
        error_category: Optional[ErrorCategory] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Write a terminal state with a sanitised failure reason."""
        self.ensure_transition(run.status, status)
        run.status = status.value
        run.finished_at = datetime.utcnow()
        if error_category is not None:
            run.error_category = error_category.value
        if error_message:
            run.error_message = redact(error_message, limit=2000)
        await self._db.commit()

    # --- recovery ----------------------------------------------------------

    @staticmethod
    def stale_cutoff(*, grace_seconds: Optional[int] = None) -> datetime:
        grace = settings.ANALYSIS_STALE_RUN_GRACE_SECONDS if grace_seconds is None else grace_seconds
        budget = settings.ANALYSIS_MAX_ANALYSIS_DURATION_SECONDS + grace
        return datetime.utcnow() - timedelta(seconds=budget)

    async def reap_stale_runs(self, *, grace_seconds: Optional[int] = None) -> int:
        """Fail runs abandoned by a dead worker. Returns how many were reaped."""
        from app.models.analysis import AnalysisRun

        cutoff = self.stale_cutoff(grace_seconds=grace_seconds)
        result = await self._db.execute(
            select(AnalysisRun).where(
                AnalysisRun.status.in_(
                    [RunStatus.PENDING.value, RunStatus.RUNNING.value, "processing"]
                ),
                func.coalesce(AnalysisRun.started_at, AnalysisRun.created_at) < cutoff,
            )
        )
        stale = list(result.scalars().all())
        if not stale:
            return 0
        now = datetime.utcnow()
        for run in stale:
            run.status = RunStatus.FAILED.value
            run.finished_at = now
            run.error_category = ErrorCategory.STALE_RUN.value
            run.error_message = (
                "The analysis worker stopped before finishing this run; it was marked "
                "failed by the stale-run recovery check. Re-run the analysis."
            )
        await self._db.commit()
        log_event("analysis_runs_reaped", count=len(stale))
        return len(stale)

    # --- queries -----------------------------------------------------------

    async def count_active_runs(
        self, *, project_id=None, owner_id=None
    ) -> int:
        """Runs still `pending`/`running`, optionally scoped to a project or owner."""
        from app.models.analysis import AnalysisRun
        from app.models.project import Project

        query = select(func.count(AnalysisRun.id)).where(
            AnalysisRun.status.in_([RunStatus.PENDING.value, RunStatus.RUNNING.value, "processing"])
        )
        if project_id is not None:
            query = query.where(AnalysisRun.project_id == project_id)
        if owner_id is not None:
            query = query.where(
                AnalysisRun.project_id.in_(select(Project.id).where(Project.owner_id == owner_id))
            )
        return int((await self._db.execute(query)).scalar() or 0)
