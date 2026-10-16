"""Request-scoped dependencies shared by every protected route.

Two things are resolved here so no endpoint repeats them:

* who the caller is (`get_current_user`, from the bearer token), and
* that the resource being touched belongs to that caller (`get_owned_project`,
  `get_owned_analysis_run`).
"""

import uuid
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import ALGORITHM
from app.db.session import get_db
from app.models.analysis import AnalysisRun, Finding
from app.models.project import Project
from app.models.user import User

# `tokenUrl` is only used to render the "Authorize" button in /docs; the real
# login is the form endpoint below it.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

# Same scheme, but a missing header is not an error: the OAuth "start" endpoint
# is reachable both signed in (to link a provider) and signed out (to sign in).
oauth2_scheme_optional = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login", auto_error=False
)

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Decode the bearer token and load the `User` it points at.

    The JWT subject is the email (see `app/api/v1/auth.py`). A malformed or
    expired token is a 401; a valid token for a deleted account is a 404.
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        if not email:
            raise _CREDENTIALS_ERROR
    except JWTError:
        # `from None`: the decoder's message (which hints at why a token failed)
        # stays out of the response.
        raise _CREDENTIALS_ERROR from None

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


async def get_optional_current_user(
    token: Optional[str] = Depends(oauth2_scheme_optional),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """The caller when a valid bearer token is present, otherwise `None`.

    Used by endpoints that behave differently when signed in but do not require
    it — currently the OAuth "start" endpoint, where a signed-in caller links
    the provider account instead of signing in with it.
    """
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        if not email:
            return None
    except JWTError:
        return None

    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_owned_project(
    project_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Project:
    """Load a project and assert the caller owns it.

    404 (missing) and 403 (someone else's) are kept distinct on purpose: the SPA
    relies on 403 to show "not authorized" instead of "not found".
    """
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()

    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if project.owner_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this project",
        )
    return project


async def get_owned_analysis_run(
    analysis_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AnalysisRun:
    """Load an analysis run, going through its project for the ownership check."""
    result = await db.execute(select(AnalysisRun).where(AnalysisRun.id == analysis_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")

    owner = await db.execute(select(Project.owner_id).where(Project.id == run.project_id))
    if owner.scalar_one_or_none() != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    return run


async def get_owned_finding(
    finding_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Finding:
    """Load one finding and assert the caller owns the project it belongs to."""
    result = await db.execute(select(Finding).where(Finding.id == finding_id))
    finding = result.scalar_one_or_none()
    if finding is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Finding not found")

    owner = await db.execute(select(Project.owner_id).where(Project.id == finding.project_id))
    if owner.scalar_one_or_none() != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this finding",
        )
    return finding
