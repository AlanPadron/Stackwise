"""Run lifecycle: allowed transitions, delayed failure recording, stale recovery."""

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.analysis.errors import ErrorCategory
from app.analysis.persistence import AnalysisPersistenceService
from app.analysis.status import (
    ACTIVE_STATUSES,
    ALLOWED_TRANSITIONS,
    TERMINAL_STATUSES,
    AnalysisStatusService,
    InvalidStatusTransition,
    RunStatus,
    normalize_status,
)
from app.db.session import AsyncSessionLocal
from app.models.analysis import AnalysisRun
from app.models.project import Project


def test_legacy_status_is_normalised():
    assert normalize_status("processing") is RunStatus.RUNNING
    assert normalize_status("COMPLETED") is RunStatus.COMPLETED
    assert normalize_status(RunStatus.FAILED) is RunStatus.FAILED


def test_unknown_status_is_rejected():
    with pytest.raises(InvalidStatusTransition):
        normalize_status("sideways")


@pytest.mark.parametrize(
    "current,target,allowed",
    [
        ("pending", RunStatus.RUNNING, True),
        ("pending", RunStatus.COMPLETED, False),
        ("pending", RunStatus.FAILED, True),
        ("running", RunStatus.COMPLETED, True),
        ("running", RunStatus.COMPLETED_WITH_ERRORS, True),
        ("running", RunStatus.FAILED, True),
        ("running", RunStatus.PENDING, False),
        ("completed", RunStatus.RUNNING, False),
        ("completed", RunStatus.FAILED, False),
        ("failed", RunStatus.RUNNING, False),
        ("cancelled", RunStatus.COMPLETED, False),
    ],
)
def test_transition_matrix(current, target, allowed):
    assert AnalysisStatusService.can_transition(current, target) is allowed
    if not allowed:
        with pytest.raises(InvalidStatusTransition):
            AnalysisStatusService.ensure_transition(current, target)


def test_terminal_states_are_terminal():
    for status in TERMINAL_STATUSES:
        assert ALLOWED_TRANSITIONS[status] == frozenset()
    assert RunStatus.PENDING in ACTIVE_STATUSES and RunStatus.RUNNING in ACTIVE_STATUSES


async def _new_run(project_id: uuid.UUID, **kwargs) -> uuid.UUID:
    async with AsyncSessionLocal() as session:
        run = await AnalysisPersistenceService(session).create_run(project_id, **kwargs)
        return run.id


async def test_mark_running_and_mark_terminal_persist(db_project):
    run_id = await _new_run(db_project)

    async with AsyncSessionLocal() as session:
        run = await AnalysisPersistenceService(session).get_run(run_id)
        assert run.status == "pending"
        service = AnalysisStatusService(session)
        await service.mark_running(run)
        assert run.status == "running"
        assert run.finished_at is None

    async with AsyncSessionLocal() as session:
        run = await AnalysisPersistenceService(session).get_run(run_id)
        assert run.status == "running"  # committed
        await AnalysisStatusService(session).mark_terminal(
            run,
            RunStatus.COMPLETED_WITH_ERRORS,
            error_category=ErrorCategory.ANALYZER_TIMEOUT,
            error_message="bandit: timed out (token=ghp_0123456789abcdefghijklmnopqrstuvwxyz)",
        )
        assert run.finished_at is not None
        assert run.error_category == "analyzer_timeout"
        # Sanitised before it is stored.
        assert "ghp_" not in run.error_message


async def test_mark_terminal_refuses_an_invalid_transition(db_project):
    run_id = await _new_run(db_project)
    async with AsyncSessionLocal() as session:
        run = await AnalysisPersistenceService(session).get_run(run_id)
        with pytest.raises(InvalidStatusTransition):
            await AnalysisStatusService(session).mark_terminal(run, RunStatus.COMPLETED)


async def test_a_terminal_run_cannot_be_marked_running_again(db_project):
    run_id = await _new_run(db_project)
    async with AsyncSessionLocal() as session:
        run = await AnalysisPersistenceService(session).get_run(run_id)
        service = AnalysisStatusService(session)
        await service.mark_running(run)
        await service.mark_terminal(run, RunStatus.COMPLETED)
        with pytest.raises(InvalidStatusTransition):
            await service.mark_running(run)


async def test_stale_runs_are_reaped_and_fresh_ones_are_left_alone(db_project):
    stale_id = await _new_run(db_project)
    fresh_id = await _new_run(db_project)
    finished_id = await _new_run(db_project)

    long_ago = datetime.utcnow() - timedelta(days=1)
    async with AsyncSessionLocal() as session:
        for run_id in (stale_id, fresh_id, finished_id):
            run = await AnalysisPersistenceService(session).get_run(run_id)
            run.started_at = long_ago
            run.created_at = long_ago
        fresh = await AnalysisPersistenceService(session).get_run(fresh_id)
        fresh.status = "running"
        fresh.created_at = datetime.utcnow()
        fresh.started_at = datetime.utcnow()
        finished = await AnalysisPersistenceService(session).get_run(finished_id)
        finished.status = "completed"
        await session.commit()

        reaped = await AnalysisStatusService(session).reap_stale_runs()
        assert reaped == 1

    async with AsyncSessionLocal() as session:
        stale = await AnalysisPersistenceService(session).get_run(stale_id)
        fresh = await AnalysisPersistenceService(session).get_run(fresh_id)
        finished = await AnalysisPersistenceService(session).get_run(finished_id)

    assert stale.status == "failed"
    assert stale.error_category == "stale_run"
    assert stale.finished_at is not None
    assert fresh.status == "running"
    assert finished.status == "completed"


async def test_active_run_counts_are_scoped(db_project):
    async with AsyncSessionLocal() as session:
        owner = (
            await session.execute(select(Project.owner_id).where(Project.id == db_project))
        ).scalar_one()
        service = AnalysisStatusService(session)

        assert await service.count_active_runs(project_id=db_project) == 0
        await _new_run(db_project)
        assert await service.count_active_runs(project_id=db_project) == 1
        assert await service.count_active_runs(owner_id=owner) == 1

        run = (
            await session.execute(
                select(AnalysisRun).where(AnalysisRun.project_id == db_project)
            )
        ).scalar_one()
        service = AnalysisStatusService(session)
        await service.mark_running(run)
        await service.mark_terminal(run, RunStatus.COMPLETED)
        assert await service.count_active_runs(project_id=db_project) == 0
