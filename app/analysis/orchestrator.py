"""Orchestration of one analysis run.

    source → workspace → extract → inventory → analyzers (per tool, in a thread)
          → normalise → deduplicate → metrics → risk → persist → terminal status

Properties this module is responsible for:

* **a run always reaches a terminal state.** Every path either persists a result
  or records `failed` with an error category; a worker that dies mid-run is
  recovered by `AnalysisStatusService.reap_stale_runs`.
* **one analyzer cannot take down the run.** A tool that is missing, times out,
  crashes or returns garbage becomes a degraded outcome
  (`completed_with_errors`) while the other tools' findings are kept.
* **cleanup always happens.** The extracted tree and the source archive are
  removed in a `finally` block on success, failure and cancellation.
* **no database connection is held while analyzers run**: the only statements are
  `pending → running` at the start and one transaction at the end.
* **bounded concurrency**: a process-wide semaphore caps how many runs execute
  at once; a run that cannot get a slot within the queue budget fails with
  `rate_limited` instead of piling up.
"""

import asyncio
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select

from app.analysis.analyzers.base import AnalyzerContext, AnalyzerOutcome, AnalyzerStatus
from app.analysis.config import AnalysisConfig, config_from_stored
from app.analysis.errors import (
    AnalysisConfigError,
    AnalysisError,
    ErrorCategory,
    ResourceLimitError,
)
from app.analysis.inventory import InventoryReport, RepositoryInspector
from app.analysis.metrics import MetricsCalculator
from app.analysis.normalize import SEVERITIES, FindingNormalizer, NormalizationResult, NormalizedFinding
from app.analysis.observability import log_event, log_exception
from app.analysis.persistence import AnalysisPersistenceService
from app.analysis.redact import redact
from app.analysis.registry import AnalyzerRegistry, build_default_registry
from app.analysis.risk import RiskEvaluator
from app.analysis.runner import AnalyzerRunner, ProcessLimits
from app.analysis.sources.archive import ArchiveSourceProvider, discard_archive
from app.analysis.status import (
    AnalysisStatusService,
    InvalidStatusTransition,
    RunStatus,
    TERMINAL_STATUSES,
    normalize_status,
)
from app.analysis.workspace import RunWorkspace
from app.core.config import settings
from app.models.analysis import AnalysisRun

_semaphore_lock = threading.Lock()
_semaphore: Optional[asyncio.Semaphore] = None
_semaphore_limit: Optional[int] = None


def _semaphore_for(limit: int) -> asyncio.Semaphore:
    """Process-wide execution slots, recreated when the configured limit changes."""
    global _semaphore, _semaphore_limit
    with _semaphore_lock:
        if _semaphore is None or _semaphore_limit != limit:
            _semaphore = asyncio.Semaphore(max(1, limit))
            _semaphore_limit = limit
        return _semaphore


def reset_concurrency_limit() -> None:
    """Drop the cached semaphore (configuration changed, tests)."""
    global _semaphore, _semaphore_limit
    with _semaphore_lock:
        _semaphore = None
        _semaphore_limit = None


@dataclass(frozen=True)
class PendingSource:
    """A source archive waiting to be acquired, owned by the caller."""

    path: Path
    source_type: str = "zip"
    origin: Optional[str] = None


@dataclass
class PipelineResult:
    status: RunStatus
    findings: tuple[NormalizedFinding, ...]
    summary: dict[str, Any]
    metrics: dict[str, Any]
    risk: dict[str, Any]
    tool_versions: dict[str, Any]
    duration_seconds: float
    source_hash: Optional[str]
    error_category: Optional[ErrorCategory] = None
    error_message: Optional[str] = None
    inventory: Optional[InventoryReport] = None
    outcomes: tuple[AnalyzerOutcome, ...] = field(default=())
    engine_version: Optional[str] = None
    config_version: Optional[str] = None
    config_hash: Optional[str] = None


class AnalysisOrchestrator:
    """Runs the pipeline for one `AnalysisRun`."""

    def __init__(
        self,
        *,
        registry: Optional[AnalyzerRegistry] = None,
        session_factory=None,
        platform_settings=settings,
    ):
        self._registry = registry or build_default_registry()
        self._session_factory = session_factory
        self._settings = platform_settings

    @property
    def registry(self) -> AnalyzerRegistry:
        return self._registry

    # --- entry point -------------------------------------------------------

    async def execute(self, run_id: uuid.UUID, source: PendingSource) -> None:
        """Execute a run end to end. Never raises; failures are recorded."""
        from app.db.session import AsyncSessionLocal

        session_factory = self._session_factory or AsyncSessionLocal
        correlation = str(run_id)

        try:
            caller = session_factory()
        except Exception as exc:  # noqa: BLE001 - the session factory itself failed
            log_exception("analysis_session_unavailable", exc, run_id=correlation)
            self._discard_source(source)
            return

        async with caller as db:
            persistence = AnalysisPersistenceService(db)
            run = await persistence.get_run(run_id)
            if run is None:
                log_event("analysis_run_missing", level=30, run_id=correlation)
                self._discard_source(source)
                return

            try:
                current = normalize_status(run.status)
            except InvalidStatusTransition as exc:
                log_event("analysis_run_unknown_status", level=30, run_id=correlation, error=str(exc))
                self._discard_source(source)
                return
            if current in TERMINAL_STATUSES:
                log_event("analysis_run_already_finished", run_id=correlation, status=current.value)
                self._discard_source(source)
                return

            try:
                config = config_from_stored(
                    run.analysis_config
                    if run.analysis_config is not None
                    else await persistence.get_project_config(run.project_id)
                )
            except AnalysisConfigError as exc:
                log_event("analysis_config_rejected", level=30, run_id=correlation, error=str(exc))
                await self._fail(db, run, ErrorCategory.CONFIGURATION, str(exc))
                self._discard_source(source)
                return

            status_service = AnalysisStatusService(db)
            try:
                await status_service.mark_running(run)
                log_event(
                    "analysis_started",
                    run_id=correlation,
                    project_id=str(run.project_id),
                    source_type=source.source_type,
                    config_hash=config.hash()[:12],
                )
                result = await self._guarded(run, source, config)
            except AnalysisError as exc:
                log_event(
                    "analysis_failed",
                    level=40,
                    run_id=correlation,
                    error_category=exc.category.value,
                    error=str(exc),
                )
                await self._fail(db, run, exc.category, str(exc))
                return
            except Exception as exc:  # noqa: BLE001 - the run must end somewhere
                log_exception("analysis_orchestration_failure", exc, run_id=correlation)
                await self._fail(db, run, ErrorCategory.ORCHESTRATION, str(exc))
                return
            finally:
                self._discard_source(source)

            try:
                await persistence.persist_results(
                    run,
                    status=result.status,
                    findings=result.findings,
                    summary=result.summary,
                    metrics=result.metrics,
                    risk=result.risk,
                    tool_versions=result.tool_versions,
                    source_hash=result.source_hash,
                    duration_seconds=result.duration_seconds,
                    error_category=result.error_category.value if result.error_category else None,
                    error_message=result.error_message,
                    engine_version=result.engine_version,
                    config_version=result.config_version,
                    config_hash=result.config_hash,
                )
            except Exception as exc:  # noqa: BLE001 - a DB failure must not hang the run
                log_exception("analysis_persistence_failure", exc, run_id=correlation)
                await self._fail(db, run, ErrorCategory.PERSISTENCE, str(exc))
                return

            log_event(
                "analysis_finished",
                run_id=correlation,
                status=result.status.value,
                findings=len(result.findings),
                duration_seconds=round(result.duration_seconds, 3),
                files_analyzed=result.metrics.get("files", {}).get("analyzed"),
            )

    # --- pipeline ----------------------------------------------------------

    async def _guarded(
        self, run: AnalysisRun, source: PendingSource, config: AnalysisConfig
    ) -> PipelineResult:
        """_pipeline behind the process-wide concurrency limit."""
        semaphore = _semaphore_for(self._settings.ANALYSIS_MAX_CONCURRENT_RUNS)
        try:
            await asyncio.wait_for(
                semaphore.acquire(), timeout=self._settings.ANALYSIS_QUEUE_WAIT_SECONDS
            )
        except asyncio.TimeoutError as exc:
            raise ResourceLimitError(
                "The analysis queue is full; retry when the running analyses finish"
            ) from exc
        try:
            return await self._pipeline(run, source, config)
        finally:
            semaphore.release()

    async def _pipeline(
        self, run: AnalysisRun, source: PendingSource, config: AnalysisConfig
    ) -> PipelineResult:
        started = time.monotonic()
        workspace = RunWorkspace.create()
        try:
            provider = ArchiveSourceProvider(
                source.path,
                config=config,
                source_type=source.source_type,
                origin=source.origin,
            )
            snapshot = await asyncio.to_thread(provider.acquire, workspace)

            inspector = RepositoryInspector(snapshot.root, config, self._registry)
            inventory = await asyncio.to_thread(inspector.inspect)
            log_event(
                "analysis_inventory",
                run_id=str(run.id),
                discovered=inventory.stats.discovered,
                analyzed=inventory.stats.analyzed,
                skipped=inventory.stats.skipped,
                failed=inventory.stats.failed,
                languages=list(inventory.languages),
            )

            deadline = started + config.max_analysis_duration_seconds
            outcomes = await self._run_analyzers(workspace, snapshot.root, inventory, config, deadline)
            duration = time.monotonic() - started

            normalization = FindingNormalizer(
                snapshot.root, max_findings=config.max_findings_per_run
            ).normalize_all(outcomes)
            metrics = MetricsCalculator(
                config=config,
                inventory=inventory,
                outcomes=outcomes,
                normalization=normalization,
                source_hash=snapshot.content_hash,
                duration_seconds=duration,
            ).calculate()
            risk = RiskEvaluator(
                config=config,
                registry=self._registry,
                findings=normalization.findings,
                outcomes=outcomes,
            ).evaluate()
            status, error_category, error_message = _final_status(outcomes)
            tool_versions = {
                outcome.analyzer: outcome.version for outcome in outcomes if outcome.version
            }

            return PipelineResult(
                status=status,
                findings=normalization.findings,
                summary=_summary(normalization, inventory, outcomes, config),
                metrics=metrics,
                risk=risk,
                tool_versions=tool_versions,
                duration_seconds=duration,
                source_hash=snapshot.content_hash,
                error_category=error_category,
                error_message=error_message,
                inventory=inventory,
                outcomes=outcomes,
                engine_version=config.engine_version,
                config_version=config.config_version,
                config_hash=config.hash(),
            )
        finally:
            workspace.cleanup()

    async def _run_analyzers(
        self,
        workspace: RunWorkspace,
        root: Path,
        inventory: InventoryReport,
        config: AnalysisConfig,
        deadline: float,
    ) -> tuple[AnalyzerOutcome, ...]:
        """Run every applicable analyzer; sequential and independent.

        Sequential on purpose: the analyzers are CPU-bound processes sharing one
        container, and running them one at a time keeps the memory ceiling
        meaningful and the timeline predictable.
        """
        runner = AnalyzerRunner(
            workspace_home=workspace.home, workspace_tmp=workspace.tmp, workdir=workspace.workdir
        )
        runner.apply_limits(
            ProcessLimits(
                timeout_seconds=config.analyzer_timeout_seconds,
                max_output_bytes=config.max_analyzer_output_bytes,
                memory_mb=config.analyzer_memory_mb,
                cpu_seconds=config.analyzer_cpu_seconds,
            )
        )

        applicable = [
            name
            for name in self._registry.names()
            if name in config.enabled_analyzers and inventory.paths_for(name)
        ]
        outcomes: list[AnalyzerOutcome] = []
        language = inventory.languages[0] if inventory.languages else "python"

        for name in applicable:
            entry = self._registry.get(name)
            if time.monotonic() >= deadline:
                outcomes.append(
                    AnalyzerOutcome(
                        analyzer=name,
                        status=AnalyzerStatus.TIMEOUT,
                        message="skipped: the analysis time budget was exhausted",
                    )
                )
                log_event("analyzer_skipped_budget", level=30, analyzer=name)
                continue

            context = AnalyzerContext(
                root=root,
                cwd=workspace.workdir,
                paths=inventory.paths_for(name),
                config=config,
                runner=runner,
                language=language,
            )
            analyzer = entry.factory(context)
            try:
                # The adapter blocks on `subprocess.wait`; a worker thread keeps the
                # event loop free (and the timeout independent of request traffic).
                outcome = await asyncio.to_thread(analyzer.analyze, context)
            except Exception as exc:  # noqa: BLE001 - one analyzer must not fail the run
                log_exception("analyzer_crashed", exc, analyzer=name)
                outcome = AnalyzerOutcome(
                    analyzer=name,
                    status=AnalyzerStatus.EXECUTION_ERROR,
                    message=redact(str(exc), limit=300),
                )
            log_event(
                "analyzer_finished",
                analyzer=name,
                status=outcome.status.value,
                findings=len(outcome.findings),
                duration_seconds=round(outcome.duration_seconds, 3),
            )
            outcomes.append(outcome)

        return tuple(outcomes)

    # --- helpers -----------------------------------------------------------

    async def _fail(
        self, db, run: AnalysisRun, category: ErrorCategory, message: str
    ) -> None:
        """Record a terminal failure, reloading the row after a rollback.

        The reload matters: `rollback()` expires the instance, and touching an
        expired attribute in async SQLAlchemy would raise instead of failing the
        run cleanly.
        """
        run_id = run.id
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001 - already broken transaction
            pass
        try:
            result = await db.execute(select(AnalysisRun).where(AnalysisRun.id == run_id))
            fresh = result.scalar_one_or_none()
            if fresh is None:
                return
            if normalize_status(fresh.status) in TERMINAL_STATUSES:
                return
            await AnalysisStatusService(db).mark_terminal(
                fresh, RunStatus.FAILED, error_category=category, error_message=message
            )
        except Exception as exc:  # noqa: BLE001 - last resort
            log_exception("analysis_failure_record_failed", exc, run_id=str(run_id))

    @staticmethod
    def _discard_source(source: PendingSource) -> None:
        """Delete the queued archive; the extracted tree is the workspace's job."""
        discard_archive(source.path)


def _final_status(outcomes: tuple[AnalyzerOutcome, ...]) -> tuple[RunStatus, Optional[ErrorCategory], Optional[str]]:
    failed = [outcome for outcome in outcomes if outcome.status.failed]
    succeeded = [outcome for outcome in outcomes if outcome.succeeded]
    if not failed:
        return RunStatus.COMPLETED, None, None
    message = "; ".join(
        f"{outcome.analyzer}: {outcome.message or outcome.status.value}" for outcome in failed
    )
    category = failed[0].status.error_category or ErrorCategory.ANALYZER_EXECUTION
    if not succeeded:
        return RunStatus.FAILED, category, message
    return RunStatus.COMPLETED_WITH_ERRORS, category, message


def _summary(
    normalization: NormalizationResult,
    inventory: InventoryReport,
    outcomes: tuple[AnalyzerOutcome, ...],
    config: AnalysisConfig,
) -> dict[str, Any]:
    findings = normalization.findings
    severity_counts = {severity: 0 for severity in SEVERITIES}
    category_counts: dict[str, int] = {}
    analyzer_counts: dict[str, int] = {}
    for finding in findings:
        severity_counts[finding.severity] = severity_counts.get(finding.severity, 0) + 1
        category_counts[finding.category] = category_counts.get(finding.category, 0) + 1
        analyzer_counts[finding.tool] = analyzer_counts.get(finding.tool, 0) + 1

    failed = [outcome for outcome in outcomes if outcome.status.failed]
    succeeded = [outcome for outcome in outcomes if outcome.succeeded]
    return {
        "total_findings": len(findings),
        "severity_counts": severity_counts,
        "category_counts": dict(sorted(category_counts.items())),
        "analyzer_counts": dict(sorted(analyzer_counts.items())),
        "files": {
            "discovered": inventory.stats.discovered,
            "analyzed": inventory.stats.analyzed,
            "skipped": inventory.stats.skipped,
            "failed": inventory.stats.failed,
        },
        "analyzers": {
            "applicable": len(outcomes),
            "succeeded": len(succeeded),
            "failed": len(failed),
        },
        "duplicates_removed": normalization.duplicates_removed,
        "dropped_findings": normalization.dropped,
        "findings_truncated": normalization.truncated,
        "complete": not failed,
        "engine_version": config.engine_version,
        "config_hash": config.hash(),
    }

