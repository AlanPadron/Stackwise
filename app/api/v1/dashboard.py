from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func
from app.db.session import get_db
from app.models.user import User
from app.models.project import Project
from app.models.analysis import AnalysisRun, Finding
from app.api.deps import get_current_user_email
from pydantic import BaseModel
from typing import Any

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
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db)
):
    # 1. Get User
    user_res = await db.execute(select(User).where(User.email == email))
    user = user_res.scalar_one_or_none()

    # 2. Total Projects
    proj_res = await db.execute(select(func.count(Project.id)).where(Project.owner_id == user.id))
    total_projects = proj_res.scalar() or 0

    # 3. Total & Completed Analyses
    anal_res = await db.execute(select(AnalysisRun).where(AnalysisRun.project_id.in_(
        select(Project.id).where(Project.owner_id == user.id)
    )))
    analyses = anal_res.scalars().all()
    total_analyses = len(analyses)
    completed_analyses = len([a for a in analyses if a.status == "completed"])

    # 4. Total Findings & Severities
    # We use a join to get all findings for all projects of this user
    find_res = await db.execute(
        select(Finding).join(AnalysisRun).join(Project).where(Project.owner_id == user.id)
    )
    findings = find_res.scalars().all()
    total_findings = len(findings)

    severities = {"high": 0, "medium": 0, "low": 0}
    for f in findings:
        sev = f.severity.lower()
        if sev in severities:
            severities[sev] += 1

    # 5. Last Analysis Status
    last_status = None
    if analyses:
        # Sort by created_at descending
        sorted_anal = sorted(analyses, key=lambda x: x.created_at, reverse=True)
        last_status = sorted_anal[0].status

    return DashboardSummary(
        total_projects=total_projects,
        total_analyses=total_analyses,
        completed_analyses=completed_analyses,
        total_findings=total_findings,
        findings_by_severity=severities,
        last_analysis_status=last_status
    )
