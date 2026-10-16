"""End-to-end pipeline runs against a controlled project with the real analyzers.

These tests are the acceptance evidence for the engine: they run ruff, bandit and
radon as subprocesses over an extracted archive, and assert on what actually
reaches the database. When a tool is not installed the assertions fail loudly —
which is the honest outcome, since the engine's contract is "these analyzers".
"""

import uuid
from pathlib import Path

import pytest
from engine_builders import demo_python_sources
from sqlalchemy import select

from app.analysis.analyzers import bandit as bandit_module
from app.analysis.orchestrator import AnalysisOrchestrator, PendingSource
from app.analysis.persistence import AnalysisPersistenceService
from app.analysis.registry import build_default_registry
from app.analysis.runner import AnalyzerRunner
from app.analysis.status import RunStatus
from app.db.session import AsyncSessionLocal
from app.models.analysis import Finding
from app.models.project import Project


async def _start_run(db_project, *, analysis_config=None) -> uuid.UUID:
    async with AsyncSessionLocal() as session:
        run = await AnalysisPersistenceService(session).create_run(
            db_project,
            source_type="github",
            source_ref="github.com/octocat/demo",
            engine_version="test",
            analysis_config=analysis_config,
        )
        return run.id


async def _execute(run_id: uuid.UUID, archive: Path) -> None:
    orchestrator = AnalysisOrchestrator()
    await orchestrator.execute(
        run_id, PendingSource(path=Path(archive), source_type="github", origin="octocat/demo@main")
    )


async def _load(run_id: uuid.UUID):
    async with AsyncSessionLocal() as session:
        run = await AnalysisPersistenceService(session).get_run(run_id)
        findings = list(
            (
                await session.execute(
                    select(Finding).where(Finding.analysis_run_id == run_id)
                )
            )
            .scalars()
            .all()
        )
        return run, findings


@pytest.fixture
def demo_archive(make_zip) -> Path:
    return make_zip(demo_python_sources(), name="demo.zip")


async def test_full_pipeline_persists_normalized_findings(db_project, demo_archive):
    run_id = await _start_run(db_project)
    await _execute(run_id, demo_archive)

    run, findings = await _load(run_id)

    assert run.status == "completed"
    assert run.error_category is None and run.error_message is None
    assert run.duration_seconds and run.duration_seconds > 0
    assert run.summary["complete"] is True
    assert run.source_hash and len(run.source_hash) == 64
    assert set(run.tool_versions) == {"ruff", "bandit", "radon"}
    assert all(version for version in run.tool_versions.values())

    # Findings: present, canonical, and deduplicated by fingerprint.
    assert findings, "the controlled project must produce findings"
    assert run.summary["total_findings"] == len(findings)
    assert sum(run.summary["severity_counts"].values()) == len(findings)
    assert {finding.tool for finding in findings} == {"ruff", "bandit", "radon"}
    assert len({finding.fingerprint for finding in findings}) == len(findings)
    assert all(len(finding.fingerprint) == 32 for finding in findings)
    assert all(finding.category for finding in findings)
    assert all(finding.severity in {"critical", "high", "medium", "low", "info"} for finding in findings)
    assert all(finding.project_id == db_project for finding in findings)
    assert all(finding.rule_id for finding in findings)

    ruff_rules = {finding.rule_id for finding in findings if finding.tool == "ruff"}
    bandit_rules = {finding.rule_id for finding in findings if finding.tool == "bandit"}
    radon_rules = {finding.rule_id for finding in findings if finding.tool == "radon"}
    assert {"F401", "F821", "E722"} <= ruff_rules
    assert {"B602", "B324"} <= bandit_rules
    assert "complexity" in radon_rules

    undefined_name = next(finding for finding in findings if finding.rule_id == "F821")
    assert undefined_name.severity == "high" and undefined_name.category == "bug"
    assert undefined_name.file_path == "app.py"
    assert undefined_name.line_start and undefined_name.line_start > 0
    assert undefined_name.column_start and undefined_name.column_start > 0

    shell = next(finding for finding in findings if finding.rule_id == "B602")
    assert shell.confidence in {"high", "medium", "low"}
    assert shell.references and shell.references["cwe"].startswith("CWE-")

    # Paths are repository-relative: the GitHub-style wrapper directory is stripped.
    assert all(not finding.file_path.startswith("demo-main/") for finding in findings)
    assert {finding.file_path for finding in findings} <= {"app.py", "pkg/util.py"}

    # Metrics and risk are persisted next to the findings.
    metrics = run.metrics
    assert metrics["files"]["analyzed"] == 2
    assert metrics["files"]["skipped"] >= 1  # README.md is not a supported language
    assert metrics["lines"]["physical"] > 0
    assert metrics["lines"]["source"] > 0
    assert metrics["complexity"]["max"] >= 11
    assert metrics["maintainability"]["files_measured"] == 2
    assert metrics["analyzers"]["complete"] is True
    assert metrics["findings"]["by_analyzer"] == run.summary["analyzer_counts"]

    assert run.risk["overall"]["available"] is True
    assert run.risk["overall"]["index"] is not None
    assert run.risk["dimensions"]["security"]["available"] is True
    assert run.risk["algorithm_version"]

    # Cleanup: neither the extracted workspace nor the source archive survive.
    import tempfile

    assert not [path for path in Path(tempfile.gettempdir()).glob("stackwise_run_*")]
    assert not demo_archive.exists()


async def test_second_execution_of_a_finished_run_is_a_no_op(db_project, demo_archive):
    run_id = await _start_run(db_project)
    await _execute(run_id, demo_archive)
    _, first_findings = await _load(run_id)

    await _execute(run_id, demo_archive)

    run, second_findings = await _load(run_id)
    assert run.status == "completed"
    assert len(second_findings) == len(first_findings)


async def test_missing_analyzer_degrades_the_run_without_losing_other_results(
    db_project, demo_archive, monkeypatch
):
    original = AnalyzerRunner.resolve

    def resolve(executable: str):
        return None if executable == "bandit" else original(executable)

    monkeypatch.setattr(AnalyzerRunner, "resolve", staticmethod(resolve))

    run_id = await _start_run(db_project)
    await _execute(run_id, demo_archive)
    run, findings = await _load(run_id)

    assert run.status == "completed_with_errors"
    assert run.error_category == "analyzer_unavailable"
    assert run.summary["complete"] is False
    assert {finding.tool for finding in findings} == {"ruff", "radon"}
    assert run.metrics["analyzers"]["items"]["bandit"]["status"] == "unavailable"

    # No security analyzer ⇒ no overall risk indicator, no "safe" score.
    assert run.risk["dimensions"]["security"]["available"] is False
    assert run.risk["overall"]["index"] is None
    assert run.risk["overall"]["available"] is False


async def test_crashing_analyzer_is_contained(db_project, demo_archive, monkeypatch):
    def explode(self, context):
        raise RuntimeError("bandit blew up")

    monkeypatch.setattr(bandit_module.BanditAnalyzer, "analyze", explode)

    run_id = await _start_run(db_project)
    await _execute(run_id, demo_archive)
    run, findings = await _load(run_id)

    assert run.status == "completed_with_errors"
    assert run.error_category == "analyzer_execution"
    assert "bandit blew up" in run.error_message
    assert findings  # the other analyzers' results survived


async def test_invalid_archive_fails_the_run(db_project, temp_root):
    archive = temp_root / "broken.zip"
    archive.write_bytes(b"this is not a zip file")

    run_id = await _start_run(db_project)
    await _execute(run_id, archive)
    run, findings = await _load(run_id)

    assert run.status == "failed"
    assert run.error_category == "invalid_source"
    assert findings == []
    assert "ZIP" in run.error_message


async def test_persistence_is_idempotent_for_a_repeated_retry(db_project, demo_archive):
    run_id = await _start_run(db_project)
    await _execute(run_id, demo_archive)
    run, findings = await _load(run_id)

    from app.analysis.normalize import NormalizedFinding

    replayed = tuple(
        NormalizedFinding(
            tool=finding.tool,
            rule_id=finding.rule_id,
            category=finding.category,
            severity=finding.severity,
            confidence=finding.confidence,
            title=finding.title,
            message=finding.message,
            file_path=finding.file_path,
            line_start=finding.line_start,
            line_end=finding.line_end,
            column_start=finding.column_start,
            column_end=finding.column_end,
            fingerprint=finding.fingerprint,
            references=finding.references,
            metadata=finding.finding_metadata,
        )
        for finding in findings
    )

    async with AsyncSessionLocal() as session:
        service = AnalysisPersistenceService(session)
        stored = await service.get_run(run_id)
        await service.persist_results(stored, status=RunStatus.COMPLETED, findings=replayed)

    _, replayed_findings = await _load(run_id)
    assert len(replayed_findings) == len(findings)


async def test_persistence_failure_marks_the_run_failed(db_project, demo_archive, monkeypatch):
    async def boom(self, *args, **kwargs):
        raise RuntimeError("deadlock detected while writing findings")

    monkeypatch.setattr(AnalysisPersistenceService, "persist_results", boom)

    run_id = await _start_run(db_project)
    await _execute(run_id, demo_archive)
    run, _ = await _load(run_id)

    assert run.status == "failed"
    assert run.error_category == "persistence"
    assert run.finished_at is not None


async def test_database_unavailable_at_startup_leaves_the_run_recoverable(db_project, demo_archive, monkeypatch):
    def broken_session_factory():
        raise RuntimeError("connection refused: postgresql://user:pw@db/stackwise")

    run_id = await _start_run(db_project)
    orchestrator = AnalysisOrchestrator(session_factory=broken_session_factory)
    await orchestrator.execute(run_id, PendingSource(path=demo_archive, source_type="github"))

    run, _ = await _load(run_id)
    assert run.status == "pending"  # still recoverable by the stale-run reaper
    assert run.error_message is None


async def test_project_configuration_is_applied(db_project, demo_archive):
    async with AsyncSessionLocal() as session:
        project = (
            await session.execute(select(Project).where(Project.id == db_project))
        ).scalar_one()
        project.analysis_config = {"enabled_analyzers": ["ruff"], "excluded_paths": ["pkg/**"]}
        await session.commit()

    run_id = await _start_run(db_project)
    await _execute(run_id, demo_archive)
    run, findings = await _load(run_id)

    assert set(run.tool_versions) == {"ruff"}
    assert {finding.tool for finding in findings} == {"ruff"}
    assert run.metrics["exclusions"] == ["pkg/**"]
    assert all(not finding.file_path.startswith("pkg/") for finding in findings)


async def test_run_level_overrides_win_over_the_project_configuration(db_project, demo_archive):
    async with AsyncSessionLocal() as session:
        project = (
            await session.execute(select(Project).where(Project.id == db_project))
        ).scalar_one()
        project.analysis_config = {"enabled_analyzers": ["ruff"]}
        await session.commit()

    run_id = await _start_run(db_project, analysis_config={"enabled_analyzers": ["radon"]})
    await _execute(run_id, demo_archive)
    run, findings = await _load(run_id)

    assert set(run.tool_versions) == {"radon"}
    assert run.config_hash == run.metrics["config_hash"]
    assert run.metrics["limits"]["overridden"] == ["enabled_analyzers"]


def test_default_registry_is_stable():
    assert build_default_registry().names() == ("ruff", "bandit", "radon")
