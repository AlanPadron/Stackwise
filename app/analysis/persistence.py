"""Persistence of runs, findings and metrics.

Two rules shape this module:

* **short transactions.** `create_run` commits and releases its connection;
  `persist_results` is one transaction at the very end of the run. No database
  connection is held while analyzers execute.
* **idempotent writes.** `persist_results` deletes the run's existing findings
  before inserting, so re-running a pipeline for the same run (a retry, a reaper
  false positive) cannot duplicate rows. A unique constraint on
  `(analysis_run_id, fingerprint)` backs that up at the schema level.

Rows are inserted in batches; findings never carry source code, and every text
column was already redacted and bounded by the normaliser.
"""

import uuid
from datetime import datetime
from typing import Any, Optional, Sequence

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.normalize import NormalizedFinding
from app.analysis.status import RunStatus
from app.models.analysis import AnalysisRun, Finding
from app.models.project import Project

_BATCH_SIZE = 200


class AnalysisPersistenceService:
    """All database access the analysis engine needs."""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def create_run(
        self,
        project_id: uuid.UUID,
        *,
        source_type: str = "github",
        source_ref: Optional[str] = None,
        engine_version: Optional[str] = None,
        config_version: Optional[str] = None,
        config_hash: Optional[str] = None,
        analysis_config: Optional[dict[str, Any]] = None,
    ) -> AnalysisRun:
        run = AnalysisRun(
            project_id=project_id,
            status=RunStatus.PENDING.value,
            source_type=source_type,
            source_ref=source_ref,
            engine_version=engine_version,
            config_version=config_version,
            config_hash=config_hash,
            analysis_config=analysis_config,
            started_at=datetime.utcnow(),
        )
        self._db.add(run)
        await self._db.commit()
        await self._db.refresh(run)
        return run

    async def get_run(self, run_id: uuid.UUID) -> Optional[AnalysisRun]:
        result = await self._db.execute(select(AnalysisRun).where(AnalysisRun.id == run_id))
        return result.scalar_one_or_none()

    async def get_project_config(self, project_id: uuid.UUID) -> Optional[dict[str, Any]]:
        result = await self._db.execute(
            select(Project.analysis_config).where(Project.id == project_id)
        )
        return result.scalar_one_or_none()

    async def persist_results(
        self,
        run: AnalysisRun,
        *,
        status: RunStatus,
        findings: Sequence[NormalizedFinding] = (),
        summary: Optional[dict[str, Any]] = None,
        metrics: Optional[dict[str, Any]] = None,
        risk: Optional[dict[str, Any]] = None,
        tool_versions: Optional[dict[str, Any]] = None,
        source_hash: Optional[str] = None,
        duration_seconds: Optional[float] = None,
        error_category: Optional[str] = None,
        error_message: Optional[str] = None,
        engine_version: Optional[str] = None,
        config_version: Optional[str] = None,
        config_hash: Optional[str] = None,
    ) -> None:
        """Write findings, summary, metrics and the terminal status atomically.

        The engine/config identity is written here too: the orchestrator is the
        only component that knows which configuration *actually* executed, so the
        run row always agrees with `metrics.config_hash`.
        """
        # Replace-then-insert: replaying a run (a retry, a stale-run false
        # positive) leaves exactly one copy of each finding.
        await self._db.execute(delete(Finding).where(Finding.analysis_run_id == run.id))

        if findings:
            rows = [finding.as_row(run.id, run.project_id) for finding in findings]
            for start in range(0, len(rows), _BATCH_SIZE):
                await self._db.execute(insert(Finding), rows[start : start + _BATCH_SIZE])

        run.status = status.value
        run.finished_at = datetime.utcnow()
        run.summary = summary
        run.metrics = metrics
        run.risk = risk
        run.tool_versions = tool_versions
        if source_hash is not None:
            run.source_hash = source_hash
        if duration_seconds is not None:
            run.duration_seconds = round(float(duration_seconds), 3)
        if engine_version is not None:
            run.engine_version = engine_version
        if config_version is not None:
            run.config_version = config_version
        if config_hash is not None:
            run.config_hash = config_hash
        run.error_category = error_category
        run.error_message = error_message

        await self._db.commit()

