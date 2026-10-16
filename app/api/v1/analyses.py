"""Analysis endpoints: poll a run and read its findings.

Runs are started by the repository import (`POST /projects/from-repo`, see
`app/api/v1/projects.py`); this module is the reading half.

The routes are registered without a prefix because they span two resource trees
(`/projects/{id}/analyses`, `/analyses/{id}` and `/findings/{id}`).

Every route goes through `app/api/deps.py` for the ownership check, so a foreign
project/run/finding is always a 403 and never leaks existence through a 404.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.registry import default_registry
from app.analysis.status import AnalysisStatusService, RunStatus
from app.api.deps import get_owned_analysis_run, get_owned_finding, get_owned_project
from app.db.session import get_db
from app.models.analysis import CATEGORIES, SEVERITIES, AnalysisRun, Finding
from app.models.project import Project
from app.schemas.analysis import AnalysisRunResponse, FindingResponse

router = APIRouter()

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


async def _reap_stale_runs(db: AsyncSession, *, run_id=None) -> None:
    """Recovery path for runs abandoned by a dead worker (cheap when none)."""
    try:
        await AnalysisStatusService(db).reap_stale_runs()
    except Exception:  # noqa: BLE001 - never fail a read because of maintenance
        await db.rollback()
