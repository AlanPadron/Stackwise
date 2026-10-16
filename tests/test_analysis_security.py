"""Security boundaries: untrusted repositories, isolation, secrets, SSRF, config."""

import json
import os
import stat
import uuid
import zipfile
from pathlib import Path

import pytest
from api_helpers import import_and_wait
from engine_builders import demo_python_sources
from sqlalchemy import select

from app.analysis.analyzers.base import AnalyzerContext, AnalyzerOutcome, AnalyzerStatus
from app.analysis.orchestrator import AnalysisOrchestrator, PendingSource
from app.analysis.persistence import AnalysisPersistenceService
from app.analysis.registry import AnalyzerRegistry, AnalyzerSpec
from app.analysis.workspace import RunWorkspace
from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.analysis import Finding

SECRET_SOURCE = {
    "demo-main/config.py": (
        'API_TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz012345"\n'
        'DATABASE_PASSWORD = "sup3r-s3cret-value"\n'
        'PASSWORD = "hunter2-secret-value"\n'
        "import subprocess\n"
        'subprocess.run("echo hi", shell=True)\n'
    )
}


async def _start_run(db_project, *, analysis_config=None) -> uuid.UUID:
    async with AsyncSessionLocal() as session:
        run = await AnalysisPersistenceService(session).create_run(
            db_project, source_type="github", analysis_config=analysis_config
        )
        return run.id


async def _execute(run_id, archive: Path, **kwargs) -> None:
    await AnalysisOrchestrator(**kwargs).execute(
        run_id, PendingSource(path=Path(archive), source_type="github", origin="octocat/demo@main")
    )


async def _load(run_id):
    async with AsyncSessionLocal() as session:
        run = await AnalysisPersistenceService(session).get_run(run_id)
        findings = list(
            (
                await session.execute(select(Finding).where(Finding.analysis_run_id == run_id))
            )
            .scalars()
            .all()
        )
        return run, findings


# --- untrusted archives ------------------------------------------------------
#
# The archive rejections (traversal, absolute paths, symlinks/FIFOs, bombs,
# depth) are covered where the validation lives: `tests/test_analysis_archive.py`.


async def test_archive_with_shell_metacharacters_in_a_filename_is_handled_literally(db_project, temp_root, make_zip):
    """A file name is data, never a command: no shell is ever involved."""
    hostile = '; rm -rf / #.py'
    archive = make_zip({"demo-main/" + hostile: "import os\n", "demo-main/ok.py": "x = 1\n"})

    run_id = await _start_run(db_project)
    await _execute(run_id, archive)
    run, findings = await _load(run_id)

    assert run.status == "completed"
    assert hostile in {finding.file_path for finding in findings}


# --- the repository cannot influence the analysis ----------------------------


async def test_repository_configuration_files_cannot_change_what_is_checked(db_project, make_zip):
    files = {
        "demo-main/pyproject.toml": '[tool.ruff]\nselect = ["ALL"]\n',
        "demo-main/.bandit": "[bandit]\nskips = ['B602']\n",
        "demo-main/app.py": (
            "import os\n"
            'very_long_line = "' + "x" * 200 + '"\n'
            "import subprocess\n"
            'subprocess.run("echo hi", shell=True)\n'
        ),
        "demo-main/ruff.toml": 'select = ["ALL"]\n',
    }
    archive = make_zip(files)

    run_id = await _start_run(db_project)
    await _execute(run_id, archive)
    run, findings = await _load(run_id)

    assert run.status == "completed"
    rules = {(finding.tool, finding.rule_id) for finding in findings}
    # `select = ["ALL"]` would have produced E501 (line too long) and many others.
    assert ("ruff", "E501") not in rules
    # `.bandit` asking to skip B602 must not be honoured.
    assert ("bandit", "B602") in rules


async def test_repository_code_is_never_executed(db_project, temp_root, make_zip):
    marker = temp_root / "executed.marker"
    files = {
        "demo-main/setup.py": (
            "import pathlib\n"
            f"pathlib.Path({str(marker)!r}).write_text('executed')\n"
            "from setuptools import setup\n"
            "setup(name='x')\n"
        ),
        "demo-main/conftest.py": (
            "import pathlib\n"
            f"pathlib.Path({str(marker)!r}).write_text('executed')\n"
        ),
        "demo-main/app.py": "value = 1\n",
    }
    archive = make_zip(files)

    run_id = await _start_run(db_project)
    await _execute(run_id, archive)

    run, _ = await _load(run_id)
    assert run.status == "completed"
    assert not marker.exists(), "repository code must never run"


async def test_analyzer_working_directory_and_environment_are_isolated(db_project, make_zip, monkeypatch):
    """The probe analyzer records exactly what an analyzer is given."""
    observed: list[AnalyzerContext] = []
    monkeypatch.setattr(settings, "ANALYSIS_ENABLED_ANALYZERS", ["probe"])

    class ProbeAnalyzer:
        name = "probe"

        def __init__(self, context: AnalyzerContext):
            self._context = context

        def analyze(self, context: AnalyzerContext) -> AnalyzerOutcome:
            observed.append(context)
            return AnalyzerOutcome(analyzer="probe", status=AnalyzerStatus.OK)

    registry = AnalyzerRegistry()
    registry.register(
        AnalyzerSpec(
            name="probe",
            languages=frozenset({"python"}),
            category="lint",
            capabilities=frozenset({"probe"}),
            executable="true",
        ),
        ProbeAnalyzer,
    )
    archive = make_zip(demo_python_sources())

    run_id = await _start_run(db_project, analysis_config={"enabled_analyzers": ["probe"]})
    await _execute(run_id, archive, registry=registry)
    run, _ = await _load(run_id)

    assert run.status == "completed"
    assert len(observed) == 1
    context = observed[0]
    workdir = context.cwd.resolve()
    root = context.root.resolve()

    # The neutral cwd is outside the extracted repository, so a repository's
    # pyproject.toml / .bandit / .radon.cfg is never discovered by a tool.
    assert workdir != root
    assert root not in workdir.parents
    assert workdir.name == "work"
    assert root.name == "demo-main"


# --- secrets -----------------------------------------------------------------


async def test_source_secrets_never_reach_findings_or_api_responses(
    client, auth_headers, repo_import
):
    repo_import(SECRET_SOURCE)
    _, run = await import_and_wait(client, auth_headers)
    run_id = run["id"]

    payloads = [json.dumps(run)]
    findings = (
        await client.get(f"/api/v1/analyses/{run_id}/findings", headers=auth_headers)
    ).json()
    payloads.append(json.dumps(findings))

    body = " ".join(payloads)
    assert findings, "the secrets fixture must still produce findings"
    for secret in ("ghp_abcdefghijklmnopqrstuvwxyz012345", "sup3r-s3cret-value", "hunter2-secret-value"):
        assert secret not in body

    # …and they are not stored either.
    async with AsyncSessionLocal() as session:
        stored = (
            await session.execute(select(Finding).where(Finding.analysis_run_id == uuid.UUID(run_id)))
        ).scalars().all()
    dump = json.dumps(
        [
            {
                "title": finding.title,
                "message": finding.message,
                "metadata": finding.finding_metadata,
                "references": finding.references,
            }
            for finding in stored
        ]
    )
    for secret in ("ghp_abcdefghijklmnopqrstuvwxyz012345", "sup3r-s3cret-value", "hunter2-secret-value"):
        assert secret not in dump


def test_workspace_permissions_are_private():
    workspace = RunWorkspace.create()
    try:
        mode = stat.S_IMODE(os.stat(workspace.root).st_mode)
        assert mode == stat.S_IRWXU
        assert workspace.source.is_dir() and workspace.workdir.is_dir()
    finally:
        workspace.cleanup()
        assert not workspace.root.exists()


# --- resource limits at run level -------------------------------------------


async def test_findings_cap_is_enforced_and_reported(db_project, make_zip):
    archive = make_zip(demo_python_sources())
    run_id = await _start_run(db_project, analysis_config={"max_findings_per_run": 1})
    await _execute(run_id, archive)

    run, findings = await _load(run_id)

    assert len(findings) == 1
    assert run.summary["findings_truncated"] is True
    assert run.metrics["findings"]["truncated"] is True
    assert run.metrics["findings"]["dropped_by_reason"]["findings_limit_reached"] > 0


async def test_analyzer_timeout_degrades_the_run_instead_of_hanging_it(db_project, make_zip, monkeypatch):
    from app.analysis.analyzers import bandit as bandit_module

    def timing_out(self, context):
        return AnalyzerOutcome(
            analyzer=self.name,
            status=AnalyzerStatus.TIMEOUT,
            message="timed out after 60s",
        )

    monkeypatch.setattr(bandit_module.BanditAnalyzer, "analyze", timing_out)
    archive = make_zip(demo_python_sources())

    run_id = await _start_run(db_project)
    await _execute(run_id, archive)
    run, findings = await _load(run_id)

    assert run.status == "completed_with_errors"
    assert run.error_category == "analyzer_timeout"
    assert findings
    assert run.risk["overall"]["index"] is None


# --- SSRF and remote inputs --------------------------------------------------


def test_github_base_url_guard(monkeypatch):
    from app.services import github as github_service

    monkeypatch.setattr(settings, "ANALYSIS_ALLOW_PRIVATE_GIT_HOSTS", False)
    for hostile in (
        "file:///etc/passwd",
        "ftp://github.local/api",
        "http://user:pass@api.github.com",
        "http://169.254.169.254",
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://metadata.google.internal",
        "gopher://api.github.com",
    ):
        with pytest.raises(github_service.GitHubError):
            github_service.validate_base_url(hostile)

    assert github_service.validate_base_url("https://api.github.com/") == "https://api.github.com"
    # A self-hosted GitHub Enterprise is an explicit opt-in.
    monkeypatch.setattr(settings, "ANALYSIS_ALLOW_PRIVATE_GIT_HOSTS", True)
    assert github_service.validate_base_url("http://10.0.0.5/api/v3") == "http://10.0.0.5/api/v3"


def test_repository_and_ref_inputs_reject_traversal_and_encoding():
    from app.services import github as github_service

    for hostile in ("../etc", "owner/..", "owner/name/extra", "owner/name?x=1", "owner/name#frag", "owner/name%2f.."):
        with pytest.raises(github_service.GitHubError):
            github_service.validate_repository(hostile)

    assert github_service.validate_repository("octocat/hello-world") == "octocat/hello-world"

    for hostile in ("../main", "main/../master", "main//dev", "main?x=1", "feature/new thing", "main\x00"):
        with pytest.raises(github_service.GitHubError):
            github_service.validate_ref(hostile)
    assert github_service.validate_ref(None) is None
    assert github_service.validate_ref("feature/branch") == "feature/branch"
    assert github_service.validate_ref("v1.2.3") == "v1.2.3"


async def test_repository_import_refuses_a_hostile_base_url(client, auth_headers, monkeypatch):
    from app.models.oauth import OAuthAccount

    me = (await client.get("/api/v1/auth/me", headers=auth_headers)).json()
    async with AsyncSessionLocal() as session:
        session.add(
            OAuthAccount(
                user_id=uuid.UUID(me["id"]),
                provider="github",
                provider_user_id=uuid.uuid4().hex,
                provider_login="octocat",
                access_token="gh-token-must-not-leak",
            )
        )
        await session.commit()

    monkeypatch.setattr(settings, "GITHUB_API_BASE_URL", "http://169.254.169.254")
    response = await client.post(
        "/api/v1/projects/from-repo",
        json={"repository": "octocat/hello-world"},
        headers=auth_headers,
    )

    assert response.status_code == 502
    assert "gh-token-must-not-leak" not in response.text
    assert "169.254.169.254" in response.json()["detail"] or "non-public" in response.json()["detail"]


async def test_repository_import_rejects_malformed_repository_names(client, auth_headers):
    for payload in (
        {"repository": "../etc/passwd"},
        {"repository": "owner/name/extra"},
        {"repository": "owner"},
        {"repository": "owner/name", "ref": "../main"},
    ):
        response = await client.post("/api/v1/projects/from-repo", json=payload, headers=auth_headers)
        assert response.status_code == 422, payload
