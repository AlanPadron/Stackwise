"""A deleted project must not leave its runs and findings behind.

Two things delete a project: `DELETE /projects/{id}` goes through the ORM, which
cascades inside the session, and the rollback in `POST /projects/from-repo` issues
a core `delete(Project)`, which does not. Only the second one depends on the
*database* honouring the DDL's `ON DELETE CASCADE` — and SQLite does not unless
the connection asks for it (see `app/db/session.py`), so a failed repository
import left orphaned `analysis_runs` and `findings` rows that no endpoint can
reach and no user can delete.
"""

import pytest
from sqlalchemy import delete, func, select, text

from app.db.session import AsyncSessionLocal, engine
from app.models.analysis import AnalysisRun, Finding
from app.models.project import Project

sqlite_only = pytest.mark.skipif(
    engine.dialect.name != "sqlite", reason="PRAGMA foreign_keys only exists on SQLite"
)


@sqlite_only
async def test_the_connection_asks_sqlite_to_enforce_foreign_keys():
    async with AsyncSessionLocal() as session:
        assert (await session.execute(text("PRAGMA foreign_keys"))).scalar() == 1


async def test_a_core_delete_of_a_project_takes_its_runs_and_findings_with_it(db_project):
    async with AsyncSessionLocal() as session:
        run = AnalysisRun(project_id=db_project, status="completed")
        session.add(run)
        await session.flush()
        session.add(
            Finding(
                analysis_run_id=run.id,
                project_id=db_project,
                tool="ruff",
                severity="low",
                category="lint",
                title="unused import",
                message="`os` imported but unused",
                file_path="a.py",
                fingerprint="0" * 64,
            )
        )
        await session.commit()

        await session.execute(delete(Project).where(Project.id == db_project))
        await session.commit()

        runs = (
            await session.execute(
                select(func.count()).select_from(AnalysisRun).where(
                    AnalysisRun.project_id == db_project
                )
            )
        ).scalar()
        findings = (
            await session.execute(
                select(func.count()).select_from(Finding).where(
                    Finding.project_id == db_project
                )
            )
        ).scalar()

    assert runs == 0
    assert findings == 0
