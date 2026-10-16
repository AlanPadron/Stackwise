from typing import Optional

from pydantic import BaseModel, Field


class GitHubRepository(BaseModel):
    """One repository of the connected GitHub account, trimmed for the picker."""

    full_name: str
    name: str
    owner: str
    private: bool
    description: Optional[str] = None
    default_branch: Optional[str] = None
    language: Optional[str] = None
    updated_at: Optional[str] = None
    html_url: Optional[str] = None


class GitHubRepositoriesResponse(BaseModel):
    """Always 200: `connected` tells the SPA which state to render."""

    connected: bool
    login: Optional[str] = None
    repositories: list[GitHubRepository] = Field(default_factory=list)
