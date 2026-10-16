"""API contract: authentication, ownership, pagination, filters, status codes."""

import uuid

import pytest
from engine_builders import demo_python_sources
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.db.session import get_db
from app.main import app

ANALYSIS_ROUTES = (
    "/api/v1/projects/{project_id}/analyses",
    "/api/v1/analyses/{run_id}",
    "/api/v1/analyses/{run_id}/findings",
)


async def _start_and_wait(client, headers, project_id, files=None, **form) -> dict:
    """Upload an archive and wait for the run to reach a terminal state."""
    import asyncio

    response = await client.post(
        f"/api/v1/projects/{project_id}/analyses",
        headers=headers,
        files={"file": ("demo.zip", _zip_bytes(files), "application/zip")},
        data=form,
    )
    assert response.status_code == 202, response.text
    body = response.json()
    for _ in range(40):
        polled = await client.get(f"/api/v1/analyses/{body['id']}", headers=headers)
        if polled.json()["status"] not in ("pending", "running", "processing"):
            return polled.json()
        await asyncio.sleep(0.05)
    raise AssertionError(f"run never finished: {body}")


def _zip_bytes(files: dict[str, str] | None = None) -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in (files or demo_python_sources()).items():
            archive.writestr(name, content)
    return buffer.getvalue()


# --- authentication and ownership --------------------------------------------


@pytest.mark.parametrize("template", ANALYSIS_ROUTES)
async def test_analysis_routes_require_authentication(client, template):
    url = template.format(project_id=uuid.uuid4(), run_id=uuid.uuid4())
    response = await client.get(url)
    assert response.status_code == 401


async def test_starting_an_analysis_requires_authentication(client):
    response = await client.post(
        f"/api/v1/projects/{uuid.uuid4()}/analyses",
        files={"file": ("demo.zip", _zip_bytes(), "application/zip")},
    )
    assert response.status_code == 401


async def test_a_foreign_project_and_its_findings_are_forbidden(client, auth_headers, project):
    run = await _start_and_wait(client, auth_headers, project["id"])
    findings = await client.get(
        f"/api/v1/analyses/{run['id']}/findings", headers=auth_headers
    )
    finding_id = findings.json()[0]["id"]

    other = (
        await client.post(
            "/api/v1/auth/register",
            json={"email": f"intruder_{uuid.uuid4().hex}@example.com", "password": "password123"},
        )
    )
    assert other.status_code == 201
    login = await client.post(
        "/api/v1/auth/login",
        data={"username": other.json()["email"], "password": "password123"},
    )
    stranger = {"Authorization": f"Bearer {login.json()['access_token']}"}

    assert (await client.get(f"/api/v1/projects/{project['id']}", headers=stranger)).status_code == 403
    assert (await client.get(f"/api/v1/analyses/{run['id']}", headers=stranger)).status_code == 403
    assert (
        await client.get(f"/api/v1/analyses/{run['id']}/findings", headers=stranger)
    ).status_code == 403
    assert (await client.get(f"/api/v1/findings/{finding_id}", headers=stranger)).status_code == 403
    # Uploading into someone else's project is refused too.
    response = await client.post(
        f"/api/v1/projects/{project['id']}/analyses",
        headers=stranger,
        files={"file": ("demo.zip", _zip_bytes(), "application/zip")},
    )
    assert response.status_code == 403


async def test_unknown_resources_are_not_found_and_malformed_ids_are_rejected(client, auth_headers):
    missing = "00000000-0000-0000-0000-000000000000"
    assert (await client.get(f"/api/v1/analyses/{missing}", headers=auth_headers)).status_code == 404
    assert (
        await client.get(f"/api/v1/findings/{missing}", headers=auth_headers)
    ).status_code == 404
    assert (
        await client.get("/api/v1/analyses/not-a-uuid", headers=auth_headers)
    ).status_code == 422


# --- starting a run ----------------------------------------------------------


async def test_upload_returns_202_pending_and_then_completes(client, auth_headers, project):
    response = await client.post(
        f"/api/v1/projects/{project['id']}/analyses",
        headers=auth_headers,
        files={"file": ("demo.zip", _zip_bytes(), "application/zip")},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert body["source_type"] == "zip"
    assert body["source_ref"] == "demo.zip"
    assert body["engine_version"] and body["config_hash"]

    run = await _start_and_wait(client, auth_headers, project["id"])
    assert run["status"] == "completed"
    assert run["summary"]["total_findings"] >= 5
    assert run["metrics"]["files"]["analyzed"] == 2
    assert run["risk"]["algorithm_version"]
    assert set(run["tool_versions"]) == {"ruff", "bandit", "radon"}


async def test_invalid_archives_are_rejected_before_a_run_is_created(client, auth_headers, project):
    not_a_zip = await client.post(
        f"/api/v1/projects/{project['id']}/analyses",
        headers=auth_headers,
        files={"file": ("bad.zip", b"definitely not a zip", "application/zip")},
    )
    assert not_a_zip.status_code == 400

    traversal = await client.post(
        f"/api/v1/projects/{project['id']}/analyses",
        headers=auth_headers,
        files={"file": ("evil.zip", _zip_bytes({"../outside.py": "x = 1\n"}), "application/zip")},
    )
    assert traversal.status_code == 400
    assert "traversal" in traversal.json()["detail"].lower()


async def test_configuration_overrides_are_validated(client, auth_headers, project):
    cases = {
        "{not json": 422,
        '{"enabled_analyzers": ["nonexistent"]}': 422,
        '{"enabled_analyzers": []}': 422,
        '{"ruff_select": [";rm -rf /"]}': 422,
        '{"excluded_paths": ["../../etc"]}': 422,
        '{"excluded_paths": ["**"]}': 422,
        '{"excluded_paths": ["/absolute"]}': 422,
        '{"analyzer_timeout_seconds": 99999}': 422,
        '{"max_findings_per_run": 999999}': 422,
        '{"unknown_setting": 1}': 422,
    }
    for payload, expected in cases.items():
        response = await client.post(
            f"/api/v1/projects/{project['id']}/analyses",
            headers=auth_headers,
            files={"file": ("demo.zip", _zip_bytes(), "application/zip")},
            data={"config": payload},
        )
        assert response.status_code == expected, f"{payload} → {response.status_code}"


async def test_valid_overrides_are_stored_on_the_run_and_applied(client, auth_headers, project):
    run = await _start_and_wait(
        client,
        auth_headers,
        project["id"],
        config='{"enabled_analyzers": ["ruff"], "complexity_threshold": 3}',
    )
    assert run["analysis_config"] == {"enabled_analyzers": ["ruff"], "complexity_threshold": 3}
    assert set(run["tool_versions"]) == {"ruff"}
    assert run["config_hash"] == run["metrics"]["config_hash"]
    assert set(run["metrics"]["limits"]["overridden"]) == {"enabled_analyzers", "complexity_threshold"}


async def test_empty_upload_is_rejected(client, auth_headers, project):
    response = await client.post(
        f"/api/v1/projects/{project['id']}/analyses",
        headers=auth_headers,
        files={"file": ("empty.zip", b"", "application/zip")},
    )
    assert response.status_code == 400


# --- reading runs ------------------------------------------------------------


async def test_run_history_is_paginated_and_filterable(client, auth_headers, project):
    await _start_and_wait(client, auth_headers, project["id"])

    response = await client.get(
        f"/api/v1/projects/{project['id']}/analyses?limit=1", headers=auth_headers
    )
    assert response.status_code == 200
    assert response.headers["x-total-count"] == "1"
    assert len(response.json()) == 1

    completed = await client.get(
        f"/api/v1/projects/{project['id']}/analyses?status=completed", headers=auth_headers
    )
    assert len(completed.json()) == 1

    empty = await client.get(
        f"/api/v1/projects/{project['id']}/analyses?status=failed", headers=auth_headers
    )
    assert empty.json() == []

    for query in ("?status=banana", "?source_type=ftp", "?limit=9999", "?offset=-1"):
        assert (
            await client.get(f"/api/v1/projects/{project['id']}/analyses{query}", headers=auth_headers)
        ).status_code == 422


# --- reading findings --------------------------------------------------------


async def test_findings_are_paginated_with_a_total_count(client, auth_headers, project):
    run = await _start_and_wait(client, auth_headers, project["id"])

    response = await client.get(
        f"/api/v1/analyses/{run['id']}/findings?limit=2&offset=0", headers=auth_headers
    )
    assert response.status_code == 200
    page = response.json()
    assert len(page) == 2
    total = int(response.headers["x-total-count"])
    assert total == run["summary"]["total_findings"]

    rest = await client.get(
        f"/api/v1/analyses/{run['id']}/findings?limit=200&offset=2", headers=auth_headers
    )
    assert len(rest.json()) == total - 2
    assert {item["id"] for item in page}.isdisjoint({item["id"] for item in rest.json()})


async def test_finding_filters_are_validated(client, auth_headers, project):
    run = await _start_and_wait(client, auth_headers, project["id"])
    base = f"/api/v1/analyses/{run['id']}/findings"

    ruff_only = await client.get(f"{base}?tool=ruff", headers=auth_headers)
    assert ruff_only.status_code == 200
    assert ruff_only.json() and {item["tool"] for item in ruff_only.json()} == {"ruff"}

    high = await client.get(f"{base}?severity=high", headers=auth_headers)
    assert {item["severity"] for item in high.json()} == {"high"}

    by_rule = await client.get(f"{base}?rule_id=F401", headers=auth_headers)
    assert {item["rule_id"] for item in by_rule.json()} == {"F401"}

    by_category = await client.get(f"{base}?category=security", headers=auth_headers)
    assert by_category.json() and {item["category"] for item in by_category.json()} == {"security"}

    by_file = await client.get(f"{base}?file_path=app.py", headers=auth_headers)
    assert {item["file_path"] for item in by_file.json()} == {"app.py"}

    sorted_by_file = await client.get(f"{base}?sort=file&limit=5", headers=auth_headers)
    assert sorted_by_file.status_code == 200

    # `sort=severity` must be seriousness order (critical → info), not alphabetical.
    by_severity = await client.get(f"{base}?sort=severity&limit=200", headers=auth_headers)
    ranks = [
        {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}[item["severity"]]
        for item in by_severity.json()
    ]
    assert ranks == sorted(ranks), ranks

    for query in (
        "?severity=banana",
        "?category=banana",
        "?tool=banana",
        "?sort=banana",
        "?file_path=../../etc/passwd",
        "?severity=",
        "?limit=0",
    ):
        assert (await client.get(f"{base}{query}", headers=auth_headers)).status_code == 422


async def test_single_finding_endpoint_returns_the_canonical_shape(client, auth_headers, project):
    run = await _start_and_wait(client, auth_headers, project["id"])
    listed = (await client.get(f"/api/v1/analyses/{run['id']}/findings", headers=auth_headers)).json()

    response = await client.get(f"/api/v1/findings/{listed[0]['id']}", headers=auth_headers)
    assert response.status_code == 200
    finding = response.json()
    assert set(finding) >= {
        "id",
        "analysis_run_id",
        "project_id",
        "tool",
        "rule_id",
        "category",
        "severity",
        "confidence",
        "title",
        "message",
        "file_path",
        "line_start",
        "line_end",
        "column_start",
        "column_end",
        "fingerprint",
        "references",
        "finding_metadata",
        "created_at",
    }
    assert finding["project_id"] == project["id"]
    assert isinstance(finding["line_start"], int)


async def test_findings_of_an_unknown_run_are_not_found(client, auth_headers):
    missing = "00000000-0000-0000-0000-000000000000"
    assert (
        await client.get(f"/api/v1/analyses/{missing}/findings", headers=auth_headers)
    ).status_code == 404


# --- limits ------------------------------------------------------------------


async def test_rate_limit_is_enforced_on_analysis_start(client, auth_headers, project, monkeypatch):
    monkeypatch.setattr(settings, "ANALYSIS_RATE_LIMIT_PER_MINUTE", 1)
    first = await client.post(
        f"/api/v1/projects/{project['id']}/analyses",
        headers=auth_headers,
        files={"file": ("demo.zip", _zip_bytes(), "application/zip")},
    )
    assert first.status_code == 202
    second = await client.post(
        f"/api/v1/projects/{project['id']}/analyses",
        headers=auth_headers,
        files={"file": ("demo.zip", _zip_bytes(), "application/zip")},
    )
    assert second.status_code == 429
    assert second.headers["retry-after"]


async def test_in_flight_run_caps_are_enforced(client, auth_headers, project, monkeypatch):
    monkeypatch.setattr(settings, "ANALYSIS_MAX_ACTIVE_RUNS_PER_PROJECT", 0)
    response = await client.post(
        f"/api/v1/projects/{project['id']}/analyses",
        headers=auth_headers,
        files={"file": ("demo.zip", _zip_bytes(), "application/zip")},
    )
    assert response.status_code == 429


async def test_a_failed_start_does_not_leave_the_uploaded_archive_behind(
    client, auth_headers, project, monkeypatch
):
    """A request that dies after spooling the upload must still clean up."""
    import tempfile
    from pathlib import Path

    from app.analysis.persistence import AnalysisPersistenceService

    async def boom(self, *args, **kwargs):
        raise OperationalError("INSERT INTO analysis_runs", {}, Exception("database gone"))

    monkeypatch.setattr(AnalysisPersistenceService, "create_run", boom)
    zips_before = set(Path(tempfile.gettempdir()).glob("*.zip"))

    response = await client.post(
        f"/api/v1/projects/{project['id']}/analyses",
        headers=auth_headers,
        files={"file": ("demo.zip", _zip_bytes(), "application/zip")},
    )

    assert response.status_code == 503
    assert set(Path(tempfile.gettempdir()).glob("*.zip")) <= zips_before


async def test_oversized_body_is_refused(client, project, auth_headers):
    big = _zip_bytes({"demo-main/pad.py": "x = 1\n" * 2_000_000})
    assert len(big) > settings.ANALYSIS_MAX_ARCHIVE_SIZE_MB * 1024 * 1024
    response = await client.post(
        f"/api/v1/projects/{project['id']}/analyses",
        headers=auth_headers,
        files={"file": ("big.zip", big, "application/zip")},
    )
    assert response.status_code == 413


# --- health and observability ------------------------------------------------


async def test_health_endpoints_do_not_disclose_internals(client):
    for path in ("/health", "/api/v1/health"):
        response = await client.get(path)
        assert response.status_code == 200
        body = response.text
        assert settings.SECRET_KEY not in body
        assert "sqlite" not in body.lower()
        assert "postgresql" not in body.lower()
        assert "traceback" not in body.lower()

    detailed = (await client.get("/api/v1/health")).json()
    assert detailed["status"] == "ok"
    assert detailed["database"] == "ok"
    assert detailed["engine_version"]


async def test_database_failures_are_reported_without_leaking_details(client, auth_headers):
    async def broken_db():
        raise OperationalError(
            "SELECT * FROM users", {"x": 1}, Exception("connection to server at db failed")
        )

    app.dependency_overrides[get_db] = broken_db
    try:
        response = await client.get("/api/v1/projects", headers=auth_headers)
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    assert response.json() == {"detail": "The database is unavailable"}
    assert "SELECT" not in response.text


async def test_dashboard_summary_reports_the_full_severity_scale(client, auth_headers, project):
    run = await _start_and_wait(client, auth_headers, project["id"])

    response = await client.get("/api/v1/dashboard/summary", headers=auth_headers)
    assert response.status_code == 200
    summary = response.json()

    assert summary["total_projects"] >= 1
    assert summary["total_analyses"] >= 1
    assert summary["completed_analyses"] >= 1
    assert summary["total_findings"] == run["summary"]["total_findings"]
    assert set(summary["findings_by_severity"]) == {"critical", "high", "medium", "low", "info"}
    assert summary["last_analysis_status"] == "completed"
