"""Shared test fixtures.

Isolation: the whole session runs against a throwaway SQLite file in a temp
directory — `SQLALCHEMY_URL` is set before `app.core.config` is imported, so the
engine the app builds points there and no test can touch a developer's database.
Each test that needs a userspace entity creates its own user with a random email
(the existing convention in this suite), so tests never share state.

Everything else in the engine is process-local and therefore global in a test
session: the analysis rate limiter and the execution semaphore are reset per test
by `_reset_engine_state`.
"""

import asyncio
import atexit
import os
import pathlib
import shutil
import tempfile
import uuid
import zipfile

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

_TEMP_ROOT = pathlib.Path(tempfile.mkdtemp(prefix="stackwise_tests_"))
os.environ["SQLALCHEMY_URL"] = f"sqlite+aiosqlite:///{_TEMP_ROOT / 'test.db'}"
os.environ["SQLALCHEMY_ECHO"] = "false"
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost/stackwise_test")
os.environ["DEV_OAUTH_MOCK"] = "false"

# The session fixture below cleans this up too; `atexit` is the backstop for an
# interrupted run, so a test session never leaves a directory behind in /tmp.
atexit.register(lambda: shutil.rmtree(_TEMP_ROOT, ignore_errors=True))

from app.analysis.orchestrator import reset_concurrency_limit  # noqa: E402
from app.core.ratelimit import reset_agent_chat_limiter, reset_analysis_start_limiter  # noqa: E402
from app.db.session import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services import github as github_service  # noqa: E402
from engine_builders import demo_python_sources  # noqa: E402,F401


@pytest.fixture(scope="session", autouse=True)
def _create_schema():
    """Create every table once, in the temp database, before the first test."""
    import app.db.base  # noqa: F401 - registers all mappers
    from app.db.session import Base

    async def create() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create())
    yield
    # Leave no trace: close the pool and delete the throwaway database directory.
    # SQLite can hold the file handle for a moment after `dispose`, hence the retry.
    import time

    try:
        asyncio.run(engine.dispose())
    except Exception:  # noqa: BLE001 - best effort shutdown
        pass
    for _ in range(3):
        shutil.rmtree(_TEMP_ROOT, ignore_errors=True)
        if not _TEMP_ROOT.exists():
            break
        time.sleep(0.2)


@pytest.fixture(autouse=True)
def _reset_engine_state():
    reset_analysis_start_limiter()
    reset_agent_chat_limiter()
    reset_concurrency_limit()
    yield
    reset_analysis_start_limiter()
    reset_agent_chat_limiter()
    reset_concurrency_limit()


@pytest.fixture
def temp_root() -> pathlib.Path:
    """A fresh directory for a test that needs files on disk."""
    path = pathlib.Path(tempfile.mkdtemp(prefix="stackwise_test_case_", dir=_TEMP_ROOT))
    return path


@pytest.fixture
def make_zip(temp_root):
    """Build a ZIP from `{name: content}` and return its path."""

    def _make(files: dict[str, str], *, name: str = "archive.zip") -> pathlib.Path:
        path = temp_root / name
        with zipfile.ZipFile(path, "w") as archive:
            for entry, content in files.items():
                archive.writestr(entry, content)
        return path

    return _make


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield http


@pytest_asyncio.fixture
async def auth_user(client: AsyncClient) -> dict:
    """A freshly registered user: its id, its email and its bearer headers."""
    email = f"user_{uuid.uuid4().hex}@example.com"
    response = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": "password123"}
    )
    assert response.status_code == 201, response.text
    login = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": "password123"}
    )
    assert login.status_code == 200, login.text
    return {
        "id": uuid.UUID(response.json()["id"]),
        "email": email,
        "headers": {"Authorization": f"Bearer {login.json()['access_token']}"},
    }


@pytest_asyncio.fixture
async def auth_headers(auth_user: dict) -> dict[str, str]:
    """A freshly registered user's bearer headers."""
    return auth_user["headers"]


@pytest_asyncio.fixture
async def github_account(auth_user: dict) -> None:
    """Link a GitHub account to the session user: the import needs its token."""
    from app.db.session import AsyncSessionLocal
    from app.models.oauth import OAuthAccount

    async with AsyncSessionLocal() as session:
        session.add(
            OAuthAccount(
                user_id=auth_user["id"],
                provider="github",
                provider_user_id=uuid.uuid4().hex,
                provider_login="octocat",
                access_token="gh-token",
            )
        )
        await session.commit()


@pytest.fixture
def github_download(monkeypatch, make_zip):
    """Serve the GitHub zipball download from a locally built archive.

    `install(files)` swaps what the next import downloads; a fresh file is built
    per call because the pipeline deletes the archive it is handed.
    """
    chosen: dict[str, dict[str, str] | None] = {"files": None}

    def install(files: dict[str, str] | None = None) -> None:
        chosen["files"] = files

        async def download(token, full_name, ref=None):
            return str(
                make_zip(chosen["files"] or demo_python_sources(), name="snapshot.zip")
            )

        monkeypatch.setattr(github_service, "download_repository_zip", download)

    install()
    return install


@pytest_asyncio.fixture
async def repo_import(github_account, github_download):
    """The preconditions of `POST /projects/from-repo`, wired to a local archive.

    Resolves to `github_download`, so a test that needs a specific snapshot calls
    the fixture value with `{name: content}` before it imports.
    """
    return github_download


@pytest_asyncio.fixture
async def project(auth_user: dict) -> dict:
    """A project row owned by the session user.

    Projects are only *created* through the repository import now, so this seeds
    the row directly (as `db_project` does for the engine tests) and hands back
    the part of its representation the API tests read.
    """
    from app.db.session import AsyncSessionLocal
    from app.models.project import Project

    async with AsyncSessionLocal() as session:
        project = Project(owner_id=auth_user["id"], name="fixture project")
        session.add(project)
        await session.commit()
        await session.refresh(project)
        return {"id": str(project.id), "name": project.name, "description": project.description}


@pytest_asyncio.fixture
async def db_project() -> uuid.UUID:
    """A project row created straight in the database (engine tests, no HTTP)."""
    from app.db.session import AsyncSessionLocal
    from app.models.project import Project
    from app.models.user import User

    async with AsyncSessionLocal() as session:
        user = User(email=f"engine_{uuid.uuid4().hex}@example.com", password_hash="x")
        session.add(user)
        await session.commit()
        await session.refresh(user)
        project = Project(owner_id=user.id, name="engine fixture")
        session.add(project)
        await session.commit()
        await session.refresh(project)
        return project.id


def sources_zip(make_zip, files: dict[str, str] | None = None) -> pathlib.Path:
    return make_zip(files if files is not None else demo_python_sources(), name="demo.zip")
