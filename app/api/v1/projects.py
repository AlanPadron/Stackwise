"""Project CRUD. Every route is scoped to the caller's own projects."""

import logging
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.config import AnalysisConfigOverrides, overrides_for_storage, resolve_config
from app.analysis.dispatch import BackgroundTaskDispatcher
from app.analysis.errors import AnalysisConfigError
from app.analysis.orchestrator import AnalysisOrchestrator, PendingSource
from app.analysis.persistence import AnalysisPersistenceService
from app.analysis.redact import redact
from app.analysis.sources.archive import discard_archive
from app.analysis.status import AnalysisStatusService
from app.api.deps import get_current_user, get_owned_project
from app.api.v1.analyses import enforce_analysis_start_rate_limit
from app.core.config import settings
from app.db.session import get_db
from app.models.project import Project
from app.models.user import User
from app.schemas.project import (
    ProjectCreate,
    ProjectFromRepo,
    ProjectFromRepoResponse,
    ProjectResponse,
    ProjectUpdate,
)
from app.services import github as github_service
from app.services import oauth as oauth_service

router = APIRouter()

logger = logging.getLogger("stackwise.projects")


@router.post("/from-repo", response_model=ProjectFromRepoResponse, status_code=status.HTTP_201_CREATED)
async def create_project_from_repo(
    payload: ProjectFromRepo,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a project from a GitHub repository and queue its first analysis.

    The snapshot is downloaded with the caller's own GitHub token and then takes
    exactly the same path as an uploaded ZIP: `pending` run returned here, the
    pipeline runs in the background. Failure to reach GitHub is reported before
    anything is created, so a user never ends up with an empty project.
    """
    enforce_analysis_start_rate_limit(user)
    analysis_config = _resolve_config_or_422(payload.analysis_config)
    await _enforce_run_caps(db, user)

    account = await oauth_service.find_account_for_user(db, user.id, "github")
    if account is None or not account.access_token:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Connect a GitHub account before importing a repository",
        )

    try:
        zip_path = await github_service.download_repository_zip(
            account.access_token, payload.repository, payload.ref
        )
    except github_service.GitHubError as exc:
        # GitHub's own 401/403 means *its* token is stale, not this session's, so
        # it is never forwarded as a 401 — the SPA would sign the user out.
        code = (
            status.HTTP_404_NOT_FOUND
            if exc.status_code == status.HTTP_404_NOT_FOUND
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(status_code=code, detail=exc.detail) from exc

    project = Project(
        name=payload.name or payload.repository.split("/")[-1],
        description=payload.description
        or f"Imported from github.com/{payload.repository}",
        owner_id=user.id,
        analysis_config=_stored_config(payload.analysis_config),
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    # Captured now: a rollback later expires the instance, and touching an expired
    # attribute in async SQLAlchemy raises instead of failing cleanly.
    project_id = project.id

    try:
        service = AnalysisPersistenceService(db)
        run = await service.create_run(
            project_id,
            source_type="github",
            source_ref=_origin(payload.repository, payload.ref),
            engine_version=analysis_config.engine_version,
            config_version=analysis_config.config_version,
            config_hash=analysis_config.hash(),
            analysis_config=(
                payload.analysis_config.model_dump(exclude_unset=True)
                if payload.analysis_config is not None
                else None
            ),
        )
        orchestrator = AnalysisOrchestrator()
        BackgroundTaskDispatcher(background_tasks, orchestrator).dispatch(
            run.id, PendingSource(path=Path(zip_path), source_type="github", origin=run.source_ref)
        )
    except Exception as exc:  # noqa: BLE001 - report a clean 503, leave nothing behind
        logger.exception("Could not start the imported analysis for project %s", project_id)
        await db.rollback()
        # Neither the downloaded archive nor a project without its first analysis
        # should survive a failed import.
        discard_archive(zip_path)
        try:
            await db.execute(delete(Project).where(Project.id == project_id))
            await db.commit()
        except Exception:  # noqa: BLE001 - best effort cleanup
            logger.exception("Could not roll back the imported project %s", project_id)
            await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not start the analysis for this repository",
        ) from exc

    return {"project": project, "run": run}


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    project_in: ProjectCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project = Project(
        name=project_in.name,
        description=project_in.description,
        owner_id=user.id,
        analysis_config=_stored_config(project_in.analysis_config),
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Project).where(Project.owner_id == user.id).order_by(Project.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(project: Project = Depends(get_owned_project)):
    return project


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_in: ProjectUpdate,
    project: Project = Depends(get_owned_project),
    db: AsyncSession = Depends(get_db),
):
    # `exclude_unset` keeps a PATCH from wiping fields the client did not send.
    changes = project_in.model_dump(exclude_unset=True)
    if "analysis_config" in changes:
        changes["analysis_config"] = _stored_config(
            AnalysisConfigOverrides(**changes["analysis_config"])
            if changes["analysis_config"]
            else None
        )
    for field, value in changes.items():
        setattr(project, field, value)

    await db.commit()
    await db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project: Project = Depends(get_owned_project),
    db: AsyncSession = Depends(get_db),
):
    # Runs and findings go with it: the FKs are ON DELETE CASCADE and the
    # relationships declare delete-orphan.
    await db.delete(project)
    await db.commit()
    return None


# --- helpers -----------------------------------------------------------------


def _resolve_config_or_422(overrides):
    try:
        return resolve_config(overrides)
    except AnalysisConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=redact(str(exc), limit=400),
        ) from exc


def _stored_config(overrides) -> dict | None:
    """Validate an override block for storage; a bad block is a 422, not a 500."""
    if overrides is None:
        return None
    block = overrides.model_dump(exclude_none=True) if isinstance(overrides, AnalysisConfigOverrides) else overrides
    try:
        return overrides_for_storage(block)
    except AnalysisConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=redact(str(exc), limit=400),
        ) from exc
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=redact(str(exc), limit=400),
        ) from exc


async def _enforce_run_caps(db: AsyncSession, user: User) -> None:
    active = await AnalysisStatusService(db).count_active_runs(owner_id=user.id)
    if active >= settings.ANALYSIS_MAX_ACTIVE_RUNS_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="You already have the maximum number of analyses in flight",
            headers={"Retry-After": "30"},
        )


def _origin(repository: str, ref: str | None) -> str:
    origin = f"github.com/{repository}"
    return f"{origin}@{redact(ref, limit=100)}" if ref else origin
