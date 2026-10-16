"""How an accepted analysis run gets executed.

`AnalysisDispatcher` is the seam required by the deployment reality described in
docs/ANALYSIS_ENGINE.md: the API only ever *queues* a run and returns the run id,
so the same orchestration works in-process today (`BackgroundTaskDispatcher`)
and behind a real worker/queue later without touching the endpoints.

Limitation of the in-process implementation, stated plainly: the run executes in
the API worker, dies with a restart, and does not survive a serverless
invocation that outlives the response. The `pending`/`running` states,
`ANALYSIS_*` limits and `reap_stale_runs` exist so a queue-backed dispatcher can
replace it without changing the contract.
"""

import uuid
from typing import Protocol, runtime_checkable

from app.analysis.orchestrator import AnalysisOrchestrator, PendingSource


@runtime_checkable
class AnalysisDispatcher(Protocol):
    """Whatever turns an accepted run into execution."""

    def dispatch(self, run_id: uuid.UUID, source: PendingSource) -> None:
        ...


class BackgroundTaskDispatcher:
    """Runs the pipeline as a FastAPI background task in the same process."""

    def __init__(self, background_tasks, orchestrator: AnalysisOrchestrator):
        self._background_tasks = background_tasks
        self._orchestrator = orchestrator

    def dispatch(self, run_id: uuid.UUID, source: PendingSource) -> None:
        self._background_tasks.add_task(self._orchestrator.execute, run_id, source)

