"""Aggregated counters for the dashboard screen (one round trip instead of four).

The counters are computed with SQL aggregates rather than by loading every run
and finding of the user, so the cost stays flat as a user accumulates analyses.
`findings_by_severity` always carries the full canonical severity scale, with
zeros where nothing was found — a stable shape for the SPA.
"""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.analysis import SEVERITIES, AnalysisRun, Finding
from app.models.project import Project
from app.models.user import User

router = APIRouter()


class DashboardSummary(BaseModel):
    total_projects: int
    total_analyses: int
    completed_analyses: int
    total_findings: int
    findings_by_severity: dict[str, int]
    last_analysis_status: Optional[str] = None


@router.get("/summary", response_model=DashboardSummary)
async def get_dashboard_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    owned_projects = select(Project.id).where(Project.owner_id == user.id)

    total_projects = (
        await db.execute(select(func.count(Project.id)).where(Project.owner_id == user.id))
    ).scalar() or 0

    status_counts = dict(
        (
            await db.execute(
                select(AnalysisRun.status, func.count(AnalysisRun.id))
                .where(AnalysisRun.project_id.in_(owned_projects))
                .group_by(AnalysisRun.status)
            )
        ).all()
    )
    total_analyses = sum(status_counts.values())
    # A run that finished with degraded analyzers still completed its work.
    completed = status_counts.get("completed", 0) + status_counts.get("completed_with_errors", 0)

    severity_rows = (
        await db.execute(
            select(Finding.severity, func.count(Finding.id))
            .join(Project, Finding.project_id == Project.id)
            .where(Project.owner_id == user.id)
            .group_by(Finding.severity)
        )
    ).all()
    by_severity = {severity: 0 for severity in SEVERITIES}
    for severity, count in severity_rows:
        by_severity[str(severity).lower()] = by_severity.get(str(severity).lower(), 0) + count

    last_status = (
        await db.execute(
            select(AnalysisRun.status)
            .where(AnalysisRun.project_id.in_(owned_projects))
            .order_by(AnalysisRun.created_at.desc(), AnalysisRun.id)
            .limit(1)
        )
    ).scalar_one_or_none()

    return DashboardSummary(
        total_projects=total_projects,
        total_analyses=total_analyses,
        completed_analyses=completed,
        total_findings=sum(by_severity.values()),
        findings_by_severity=by_severity,
        last_analysis_status=last_status,
    )
