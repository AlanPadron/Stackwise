"""Analysis endpoints: start a run, poll it, read its findings.

The routes are registered without a prefix because they span two resource trees
(`/projects/{id}/analyses`, `/analyses/{id}` and `/findings/{id}`).

Every route goes through `app/api/deps.py` for the ownership check, so a foreign
project/run/finding is always a 403 and never leaks existence through a 404.
Starting a run is the only expensive route: it is rate limited, capped by the
number of in-flight runs per project and per user, and bounded by the request
body size before the archive is even stored.
"""

import json
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from pydantic import ValidationError
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.config import AnalysisConfigOverrides, resolve_config
from app.analysis.dispatch import BackgroundTaskDispatcher
from app.analysis.errors import AnalysisConfigError, InvalidSourceError, ResourceLimitError
from app.analysis.orchestrator import AnalysisOrchestrator, PendingSource
from app.analysis.persistence import AnalysisPersistenceService
from app.analysis.redact import redact
from app.analysis.registry import default_registry
from app.analysis.sources.archive import discard_archive, inspect_archive
from app.analysis.status import AnalysisStatusService, RunStatus
from app.api.deps import get_current_user, get_owned_analysis_run, get_owned_finding, get_owned_project
from app.core.config import settings
from app.core.ratelimit import analysis_start_limiter
from app.db.session import get_db
from app.models.analysis import CATEGORIES, SEVERITIES, AnalysisRun, Finding
from app.models.project import Project
from app.models.user import User
from app.schemas.analysis import AnalysisRunResponse, FindingResponse

router = APIRouter()

_UPLOAD_CHUNK_BYTES = 1024 * 1024
_DEFAULT_PAGE_SIZE = 50
_MAX_PAGE_SIZE = 200
_STATUS_VALUES = tuple(item.value for item in RunStatus)
# Severities are ordered by seriousness, not alphabetically: a plain column sort
# would put `info` before `low` and `medium` last.
_SEVERITY_RANK = case(
    (Finding.severity == "critical", 0),
    (Finding.severity == "high", 1),
    (Finding.severity == "medium", 2),
    (Finding.severity == "low", 3),
    (Finding.severity == "info", 4),
    else_=5,
)
_FINDING_SORTS = {
    "severity": [_SEVERITY_RANK, Finding.file_path, Finding.line_start],
    "file": [Finding.file_path, Finding.line_start, Finding.tool],
    "-created_at": [Finding.created_at.desc()],
}


# --- starting a run ----------------------------------------------------------


@router.post(
    "/projects/{project_id}/analyses",
    response_model=AnalysisRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_analysis(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    config: Optional[str] = Form(None, description="JSON analysis overrides"),
    project: Project = Depends(get_owned_project),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Accept a ZIP and return immediately with a `pending` run (202).

    Validates, in order: rate limit → configuration → in-flight run caps → body
    size → archive structure (cheap central-directory check, no extraction).
    The archive is spooled to a temp file the pipeline deletes when the run
    ends, so the background task outliving this request is safe.
    """
    enforce_analysis_start_rate_limit(user)
    overrides = _parse_overrides(config)
    # Effective configuration: this request's overrides, else the project's stored
    # block, else the platform defaults. Resolved once, before the run row is
    # written, so `config_hash` on the run describes what will actually execute.
    effective = overrides if overrides is not None else _project_overrides(project)
    analysis_config = _resolve_or_422(effective)
    stored_overrides = effective.model_dump(exclude_unset=True) if effective is not None else None
    await _enforce_run_caps(db, user=user, project_id=project.id)

    archive_path = await _spool_upload(file, limit_bytes=analysis_config.max_archive_bytes)
    try:
        inspect_archive(archive_path, analysis_config)
    except (InvalidSourceError, ResourceLimitError) as exc:
        discard_archive(archive_path)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=redact(str(exc), limit=300),
        ) from exc

    # From here the archive belongs to the pipeline, which deletes it when the
    # run ends. Until the dispatch succeeds, this request still owns it.
    try:
        service = AnalysisPersistenceService(db)
        run = await service.create_run(
            project.id,
            source_type="zip",
            source_ref=_safe_filename(file.filename),
            engine_version=analysis_config.engine_version,
            config_version=analysis_config.config_version,
            config_hash=analysis_config.hash(),
            analysis_config=stored_overrides,
        )
        orchestrator = AnalysisOrchestrator()
        BackgroundTaskDispatcher(background_tasks, orchestrator).dispatch(
            run.id, PendingSource(path=archive_path, source_type="zip", origin=run.source_ref)
        )
    except Exception:
        discard_archive(archive_path)
        raise
    return run


# --- reading runs ------------------------------------------------------------


@router.get("/projects/{project_id}/analyses", response_model=list[AnalysisRunResponse])
async def list_project_analyses(
    response: Response,
    project: Project = Depends(get_owned_project),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(_DEFAULT_PAGE_SIZE, ge=1, le=_MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
    status_filter: Optional[str] = Query(None, alias="status"),
    source_type: Optional[str] = Query(None, max_length=16),
):
    """Analysis history for a project, newest first, paginated."""
    await _reap_stale_runs(db)

    filters = [AnalysisRun.project_id == project.id]
    if status_filter is not None:
        normalized = status_filter.strip().lower()
        if normalized not in _STATUS_VALUES and normalized != "processing":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unsupported status filter: {status_filter}",
            )
        filters.append(
            AnalysisRun.status.in_([normalized, "running"] if normalized == "processing" else [normalized])
        )
    if source_type is not None:
        if source_type not in ("zip", "github"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unsupported source_type filter: {source_type}",
            )
        filters.append(AnalysisRun.source_type == source_type)

    total = (
        await db.execute(select(func.count(AnalysisRun.id)).where(*filters))
    ).scalar() or 0
    result = await db.execute(
        select(AnalysisRun)
        .where(*filters)
        .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id)
        .limit(limit)
        .offset(offset)
    )
    response.headers["X-Total-Count"] = str(total)
    return result.scalars().all()


@router.get("/analyses/{analysis_id}", response_model=AnalysisRunResponse)
async def get_analysis(
    run: AnalysisRun = Depends(get_owned_analysis_run),
    db: AsyncSession = Depends(get_db),
):
    """Polled by the SPA while a run moves pending → running → terminal."""
    await _reap_stale_runs(db, run_id=run.id)
    return run


# --- reading findings --------------------------------------------------------


@router.get("/analyses/{analysis_id}/findings", response_model=list[FindingResponse])
async def get_findings(
    response: Response,
    run: AnalysisRun = Depends(get_owned_analysis_run),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(_DEFAULT_PAGE_SIZE, ge=1, le=_MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
    severity: Optional[str] = Query(None, max_length=16),
    category: Optional[str] = Query(None, max_length=32),
    tool: Optional[str] = Query(None, max_length=64),
    rule_id: Optional[str] = Query(None, max_length=64),
    file_path: Optional[str] = Query(None, max_length=500),
    sort: str = Query("severity"),
):
    """Findings of one run, filtered and paginated; newest analysis first."""
    filters = [Finding.analysis_run_id == run.id]
    for column, value, allowed in (
        (Finding.severity, severity, SEVERITIES),
        (Finding.category, category, CATEGORIES),
        (Finding.tool, tool, default_registry().names()),
        (Finding.rule_id, rule_id, None),
    ):
        if value is None:
            continue
        cleaned = value.strip()
        if not cleaned:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Filter values must not be empty",
            )
        if allowed is not None and cleaned not in allowed:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unsupported {column.key} filter: {cleaned}",
            )
        filters.append(column == cleaned)
    if file_path is not None:
        cleaned = file_path.strip()
        if not cleaned or cleaned.startswith("/") or ".." in cleaned.split("/"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="file_path must be a repository-relative path",
            )
        filters.append(Finding.file_path == cleaned)

    if sort not in _FINDING_SORTS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported sort: {sort}",
        )

    total = (await db.execute(select(func.count(Finding.id)).where(*filters))).scalar() or 0
    result = await db.execute(
        select(Finding)
        .where(*filters)
        .order_by(*_FINDING_SORTS[sort], Finding.id)
        .limit(limit)
        .offset(offset)
    )
    response.headers["X-Total-Count"] = str(total)
    return result.scalars().all()


@router.get("/findings/{finding_id}", response_model=FindingResponse)
async def get_finding(finding: Finding = Depends(get_owned_finding)):
    """One finding, only if the caller owns the project it belongs to."""
    return finding


# --- helpers -----------------------------------------------------------------


def enforce_analysis_start_rate_limit(user: User) -> None:
    allowed, retry_after = analysis_start_limiter().check(str(user.id))
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many analysis requests; slow down",
            headers={"Retry-After": str(max(1, int(retry_after) + 1))},
        )


def _parse_overrides(raw: Optional[str]) -> Optional[AnalysisConfigOverrides]:
    if raw is None or not raw.strip():
        return None
    if len(raw) > 4096:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Analysis configuration is too large",
        )
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Analysis configuration must be valid JSON",
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Analysis configuration must be a JSON object",
        )
    try:
        return AnalysisConfigOverrides(**payload)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=redact(str(exc), limit=400),
        ) from exc


def _resolve_or_422(overrides: Optional[AnalysisConfigOverrides]):
    try:
        return resolve_config(overrides)
    except AnalysisConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=redact(str(exc), limit=400),
        ) from exc


def _project_overrides(project: Project) -> Optional[AnalysisConfigOverrides]:
    """The project's stored analysis block, re-validated for this run."""
    if not project.analysis_config:
        return None
    try:
        return AnalysisConfigOverrides(**project.analysis_config)
    except (ValidationError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=redact(f"Stored project analysis configuration is invalid: {exc}", limit=400),
        ) from exc


async def _enforce_run_caps(db: AsyncSession, *, user: User, project_id) -> None:
    status_service = AnalysisStatusService(db)
    per_project = await status_service.count_active_runs(project_id=project_id)
    if per_project >= settings.ANALYSIS_MAX_ACTIVE_RUNS_PER_PROJECT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="This project already has the maximum number of analyses in flight",
            headers={"Retry-After": "30"},
        )
    per_user = await status_service.count_active_runs(owner_id=user.id)
    if per_user >= settings.ANALYSIS_MAX_ACTIVE_RUNS_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="You already have the maximum number of analyses in flight",
            headers={"Retry-After": "30"},
        )


async def _spool_upload(file: UploadFile, *, limit_bytes: int) -> Path:
    """Stream an upload to a temp file, refusing anything over the size limit."""
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    written = 0
    try:
        while True:
            chunk = await file.read(_UPLOAD_CHUNK_BYTES)
            if not chunk:
                break
            written += len(chunk)
            if written > limit_bytes:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"The archive exceeds the {limit_bytes // (1024 * 1024)}MB limit",
                )
            handle.write(chunk)
        if written == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="The uploaded archive is empty"
            )
    except HTTPException:
        handle.close()
        discard_archive(handle.name)
        raise
    except Exception as exc:  # noqa: BLE001 - storage failure
        handle.close()
        discard_archive(handle.name)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store the uploaded archive",
        ) from exc
    handle.close()
    return Path(handle.name)


async def _reap_stale_runs(db: AsyncSession, *, run_id=None) -> None:
    """Recovery path for runs abandoned by a dead worker (cheap when none)."""
    try:
        await AnalysisStatusService(db).reap_stale_runs()
    except Exception:  # noqa: BLE001 - never fail a read because of maintenance
        await db.rollback()


def _safe_filename(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return redact(Path(value.replace("\\", "/")).name, limit=200) or None
