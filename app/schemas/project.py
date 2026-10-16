from pydantic import BaseModel, Field
from typing import Any, Optional
from uuid import UUID
from datetime import datetime

from app.analysis.config import AnalysisConfigOverrides
from app.schemas.analysis import AnalysisRunResponse

class ProjectBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)

class ProjectCreate(ProjectBase):
    analysis_config: Optional[AnalysisConfigOverrides] = None

class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    analysis_config: Optional[AnalysisConfigOverrides] = None

class ProjectResponse(ProjectBase):
    id: UUID
    owner_id: UUID
    analysis_config: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class ProjectFromRepo(BaseModel):
    """Create a project straight from a GitHub repository."""

    repository: str = Field(
        ...,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}/[A-Za-z0-9][A-Za-z0-9._-]{0,99}$",
        description="`owner/name` of the repository to import",
    )
    ref: Optional[str] = Field(
        None,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,198}$",
        description="Branch, tag or commit (no `..` segments)",
    )
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    analysis_config: Optional[AnalysisConfigOverrides] = None

class ProjectFromRepoResponse(BaseModel):
    """The new project plus the analysis run queued for it."""

    project: ProjectResponse
    run: AnalysisRunResponse
