"""API contract: authentication, ownership, pagination, filters, status codes."""

import json
import uuid

import pytest
from api_helpers import import_and_wait, import_repository, wait_for_run
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.db.session import get_db
from app.main import app

ANALYSIS_ROUTES = (
    "/api/v1/projects/{project_id}/analyses",
    "/api/v1/analyses/{run_id}",
    "/api/v1/analyses/{run_id}/findings",
)


# --- authentication and ownership --------------------------------------------


@pytest.mark.parametrize("template", ANALYSIS_ROUTES)
async def test_analysis_routes_require_authentication(client, template):
    url = template.format(project_id=uuid.uuid4(), run_id=uuid.uuid4())
    response = await client.get(url)
    assert response.status_code == 401


async def test_starting_an_analysis_requires_authentication(client):
    response = await import_repository(client, None, repository="octocat/demo")
    assert response.status_code == 401


async def test_a_foreign_project_and_its_findings_are_forbidden(
    client, auth_headers, repo_import
):
    project, run = await import_and_wait(client, auth_headers)
    findings = await client.get(
        f"/api/v1/analyses/{run['id']}/findings", headers=auth_headers
    )
    finding_id = findings.json()[0]["id"]

    other = (
        await client.post(
            "/api/v1/auth/register",
            json={"email": f"intruder_{uuid.uuid4().hex}@example.com", "password": "Probe-pass-2024"},
        )
    )
    assert other.status_code == 201
    login = await client.post(
        "/api/v1/auth/login",
        data={"username": other.json()["email"], "password": "Probe-pass-2024"},
    )
    stranger = {"Authorization": f"Bearer {login.json()['access_token']}"}

    assert (await client.get(f"/api/v1/projects/{project['id']}", headers=stranger)).status_code == 403
    assert (await client.get(f"/api/v1/analyses/{run['id']}", headers=stranger)).status_code == 403
    assert (
        await client.get(f"/api/v1/analyses/{run['id']}/findings", headers=stranger)
    ).status_code == 403
    assert (await client.get(f"/api/v1/findings/{finding_id}", headers=stranger)).status_code == 403
    # Reading is not the only thing that is scoped: acting on someone else's
    # project is refused too, and the project is still there afterwards.
    assert (await client.delete(f"/api/v1/projects/{project['id']}", headers=stranger)).status_code == 403
    assert (await client.get(f"/api/v1/projects/{project['id']}", headers=auth_headers)).status_code == 200


async def test_unknown_resources_are_not_found_and_malformed_ids_are_rejected(client, auth_headers):
    missing = "00000000-0000-0000-0000-000000000000"
    assert (await client.get(f"/api/v1/analyses/{missing}", headers=auth_headers)).status_code == 404
    assert (
        await client.get(f"/api/v1/findings/{missing}", headers=auth_headers)
    ).status_code == 404
    assert (
        await client.get("/api/v1/analyses/not-a-uuid", headers=auth_headers)
    ).status_code == 422


# --- starting a run (repository import) --------------------------------------


async def test_import_queues_a_pending_run_that_then_completes(client, auth_headers, repo_import):
    response = await import_repository(client, auth_headers, repository="octocat/demo")

    assert response.status_code == 201, response.text
    body = response.json()
    run = body["run"]
    assert run["status"] == "pending"
    assert run["source_type"] == "github"
    assert run["source_ref"] == "github.com/octocat/demo"
    assert run["engine_version"] and run["config_hash"]
    assert body["project"]["name"] == "demo"

    finished = await wait_for_run(client, auth_headers, run["id"])
    assert finished["status"] == "completed"
    assert finished["summary"]["total_findings"] >= 5
    assert finished["metrics"]["files"]["analyzed"] == 2
    assert finished["risk"]["algorithm_version"]
    assert set(finished["tool_versions"]) == {"ruff", "bandit", "radon"}


async def test_configuration_overrides_are_validated(client, auth_headers, repo_import):
    cases = {
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
        response = await import_repository(
            client, auth_headers, analysis_config=json.loads(payload)
        )
        assert response.status_code == expected, f"{payload} → {response.status_code}"

    # A body that is not JSON at all is refused before the handler runs.
    malformed = await client.post(
        "/api/v1/projects/from-repo",
        content=b"{not json",
        headers={**auth_headers, "Content-Type": "application/json"},
    )
    assert malformed.status_code == 422


async def test_valid_overrides_are_stored_on_the_run_and_applied(client, auth_headers, repo_import):
    _, run = await import_and_wait(
        client,
        auth_headers,
        analysis_config={"enabled_analyzers": ["ruff"], "complexity_threshold": 3},
    )
    assert run["analysis_config"] == {"enabled_analyzers": ["ruff"], "complexity_threshold": 3}
    assert set(run["tool_versions"]) == {"ruff"}
    assert run["config_hash"] == run["metrics"]["config_hash"]
    assert set(run["metrics"]["limits"]["overridden"]) == {"enabled_analyzers", "complexity_threshold"}


# --- reading runs ------------------------------------------------------------


async def test_run_history_is_paginated_and_filterable(client, auth_headers, repo_import):
    project, _ = await import_and_wait(client, auth_headers)

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


async def test_findings_are_paginated_with_a_total_count(client, auth_headers, repo_import):
    _, run = await import_and_wait(client, auth_headers)

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


async def test_finding_filters_are_validated(client, auth_headers, repo_import):
    _, run = await import_and_wait(client, auth_headers)
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


async def test_single_finding_endpoint_returns_the_canonical_shape(client, auth_headers, repo_import):
    project, run = await import_and_wait(client, auth_headers)
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


async def test_rate_limit_is_enforced_on_analysis_start(client, auth_headers, repo_import, monkeypatch):
    monkeypatch.setattr(settings, "ANALYSIS_RATE_LIMIT_PER_MINUTE", 1)
    first = await import_repository(client, auth_headers, repository="octocat/one")
    assert first.status_code == 201
    second = await import_repository(client, auth_headers, repository="octocat/two")
    assert second.status_code == 429
    assert second.headers["retry-after"]


async def test_in_flight_run_caps_are_enforced(client, auth_headers, repo_import, monkeypatch):
    monkeypatch.setattr(settings, "ANALYSIS_MAX_ACTIVE_RUNS_PER_USER", 0)
    response = await import_repository(client, auth_headers, repository="octocat/demo")
    assert response.status_code == 429
    assert response.headers["retry-after"]


async def test_a_failed_import_does_not_leave_the_downloaded_snapshot_behind(
    client, auth_headers, repo_import, temp_root, monkeypatch
):
    """A request that dies after the download must still clean up after itself."""
    from app.analysis.persistence import AnalysisPersistenceService

    async def boom(self, *args, **kwargs):
        raise OperationalError("INSERT INTO analysis_runs", {}, Exception("database gone"))

    monkeypatch.setattr(AnalysisPersistenceService, "create_run", boom)

    response = await import_repository(client, auth_headers, repository="octocat/demo")

    assert response.status_code == 503
    # Neither the downloaded snapshot nor the project it was for is left behind.
    assert not (temp_root / "snapshot.zip").exists()
    assert (await client.get("/api/v1/projects", headers=auth_headers)).json() == []


async def test_oversized_body_is_refused(client, auth_headers):
    big = "x" * (settings.ANALYSIS_MAX_REQUEST_BODY_BYTES + 1)
    response = await client.post(
        "/api/v1/projects/from-repo",
        json={"repository": "octocat/demo", "description": big},
        headers=auth_headers,
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


async def test_dashboard_summary_reports_the_full_severity_scale(client, auth_headers, repo_import):
    _, run = await import_and_wait(client, auth_headers)

    response = await client.get("/api/v1/dashboard/summary", headers=auth_headers)
    assert response.status_code == 200
    summary = response.json()

    assert summary["total_projects"] >= 1
    assert summary["total_analyses"] >= 1
    assert summary["completed_analyses"] >= 1
    assert summary["total_findings"] == run["summary"]["total_findings"]
    assert set(summary["findings_by_severity"]) == {"critical", "high", "medium", "low", "info"}
    assert summary["last_analysis_status"] == "completed"
