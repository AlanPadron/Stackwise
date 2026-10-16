"""GitHub repository picker: the repositories the connected account can import."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.github import GitHubRepositoriesResponse
from app.services import github as github_service
from app.services import oauth as oauth_service

router = APIRouter()


@router.get("/repositories", response_model=GitHubRepositoriesResponse)
async def list_repositories(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Repositories of the caller's linked GitHub account.

    Always 200: "not connected yet" is a normal state the SPA renders as a
    call to action, not an error.
    """
    account = await oauth_service.find_account_for_user(db, user.id, "github")
    if account is None or not account.access_token:
        return {"connected": False, "login": None, "repositories": []}

    try:
        repositories = await github_service.list_repositories(account.access_token)
    except github_service.GitHubError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.detail
        ) from exc

    return {
        "connected": True,
        "login": account.provider_login,
        "repositories": repositories,
    }
