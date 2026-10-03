from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.db.session import get_db
from app.models.project import Project
from app.schemas.project import ProjectCreate, ProjectResponse, ProjectUpdate
from app.api.deps import get_current_user_email
from app.models.user import User

router = APIRouter()

@router.post("/", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    project_in: ProjectCreate,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db)
):
    # Find user
    user_res = await db.execute(select(User).where(User.email == email))
    user = user_res.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    project = Project(
        name=project_in.name,
        description=project_in.description,
        owner_id=user.id
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project

@router.get("/", response_model=list[ProjectResponse])
async def list_projects(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db)
):
    user_res = await db.execute(select(User).where(User.email == email))
    user = user_res.scalar_one_or_none()

    result = await db.execute(select(Project).where(Project.owner_id == user.id))
    return result.scalars().all()

@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db)
):
    user_res = await db.execute(select(User).where(User.email == email))
    user = user_res.scalar_one_or_none()

    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to access this project")

    return project

@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    project_in: ProjectUpdate,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db)
):
    user_res = await db.execute(select(User).where(User.email == email))
    user = user_res.scalar_one_or_none()

    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to modify this project")

    for field, value in project_in.model_dump(exclude_unset=True).items():
        setattr(project, field, value)

    await db.commit()
    await db.refresh(project)
    return project

@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db)
):
    user_res = await db.execute(select(User).where(User.email == email))
    user = user_res.scalar_one_or_none()

    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to delete this project")

    await db.delete(project)
    await db.commit()
    return None
