from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.db.session import get_db
from app.models.project import Project
from app.models.analysis import AnalysisRun, Finding
from app.schemas.analysis import AnalysisRunResponse, FindingResponse
from app.api.deps import get_current_user_email
from app.services.analysis_service import AnalysisService
from app.models.user import User
import shutil
import tempfile
import os
import uuid

router = APIRouter()

@router.post("/projects/{project_id}/analyses", response_model=AnalysisRunResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_analysis(
    project_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db)
):
    # 1. Ownership check
    user_res = await db.execute(select(User).where(User.email == email))
    user = user_res.scalar_one_or_none()

    proj_res = await db.execute(select(Project).where(Project.id == project_id))
    project = proj_res.scalar_one_or_none()

    if not project or project.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Project not found or unauthorized")

    # 2. Save ZIP to a temporary location for processing
    temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    try:
        shutil.copyfileobj(file.file, temp_zip)
        temp_zip.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save upload: {str(e)}")

    # 3. Start analysis record
    service = AnalysisService(db)
    run = await service.start_analysis(project.id, temp_zip.name)

    # 4. Queue the heavy lifting in background
    background_tasks.add_task(service.execute_analysis_pipeline, run.id, temp_zip.name)

    return run

@router.get("/analyses/{analysis_id}", response_model=AnalysisRunResponse)
async def get_analysis(
    analysis_id: uuid.UUID,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(AnalysisRun).where(AnalysisRun.id == analysis_id))
    run = res.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Analysis not found")

    # Ownership check
    proj_res = await db.execute(select(Project).where(Project.id == run.project_id))
    project = proj_res.scalar_one_or_none()

    user_res = await db.execute(select(User).where(User.email == email))
    user = user_res.scalar_one_or_none()

    if not project or project.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Unauthorized")

    return run

@router.get("/analyses/{analysis_id}/findings", response_model=list[FindingResponse])
async def get_findings(
    analysis_id: uuid.UUID,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db)
):
    res = await db.execute(select(AnalysisRun).where(AnalysisRun.id == analysis_id))
    run = res.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Analysis not found")

    # Ownership check
    proj_res = await db.execute(select(Project).where(Project.id == run.project_id))
    project = proj_res.scalar_one_or_none()
    user_res = await db.execute(select(User).where(User.email == email))
    user = user_res.scalar_one_or_none()

    if not project or project.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Unauthorized")

    findings_res = await db.execute(select(Finding).where(Finding.analysis_run_id == run.id))
    return findings_res.scalars().all()

@router.get("/projects/{project_id}/analyses", response_model=list[AnalysisRunResponse])
async def list_project_analyses(
    project_id: uuid.UUID,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db)
):
    user_res = await db.execute(select(User).where(User.email == email))
    user = user_res.scalar_one_or_none()

    proj_res = await db.execute(select(Project).where(Project.id == project_id))
    project = proj_res.scalar_one_or_none()

    if not project or project.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Unauthorized")

    res = await db.execute(select(AnalysisRun).where(AnalysisRun.project_id == project.id))
    return res.scalars().all()
