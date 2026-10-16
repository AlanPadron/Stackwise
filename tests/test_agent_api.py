"""The agent endpoints: honest status, ownership, bounds and the real context.

The model is not installed here (by design — see requirements-agent.txt), so the
unavailable path is exercised against the real configuration, and the generation
path is exercised through the seam with a recording backend, because what matters
there is the *contract*: which findings reach the model and what the endpoint
returns.
"""

import asyncio
import io
import uuid
import zipfile

import pytest
from engine_builders import demo_python_sources

from app.agent.backend import ChatMessage, UnavailableBackend
from app.agent.qwen import missing_dependencies
from app.api.v1.agent import agent_backend
from app.core.config import settings
from app.main import app

INSTALL_HINT = "requirements-agent.txt"


class _RecordingBackend:
    """Stands in for the model: records what it was asked, then answers."""

    name = "fake"
    model = "fake-model"

    def __init__(self, answer: str = "B608 is a string-built SQL query.") -> None:
        self.answer = answer
        self.calls: list[list[ChatMessage]] = []

    def unavailable_reason(self):
        return None

    async def complete(self, messages, *, max_new_tokens: int) -> str:
        self.calls.append(list(messages))
        return self.answer


@pytest.fixture
def fake_backend():
    backend = _RecordingBackend()
    app.dependency_overrides[agent_backend] = lambda: backend
    yield backend
    app.dependency_overrides.pop(agent_backend, None)


@pytest.fixture
def unavailable_backend():
    backend = UnavailableBackend(
        name="qwen",
        model="Qwen/Qwen2.5-0.5B-Instruct",
        reason="the agent model is not installed: run `pip install -r requirements-agent.txt`",
    )
    app.dependency_overrides[agent_backend] = lambda: backend
    yield backend
    app.dependency_overrides.pop(agent_backend, None)


async def _completed_run(client, headers, project_id) -> dict:
    """A finished analysis with real analyzer output (ruff/bandit/radon)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in demo_python_sources().items():
            archive.writestr(name, content)

    response = await client.post(
        f"/api/v1/projects/{project_id}/analyses",
        headers=headers,
        files={"file": ("demo.zip", buffer.getvalue(), "application/zip")},
    )
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    for _ in range(40):
        run = (await client.get(f"/api/v1/analyses/{run_id}", headers=headers)).json()
        if run["status"] not in ("pending", "running", "processing"):
            return run
        await asyncio.sleep(0.05)
    raise AssertionError("run never finished")


async def _second_user_headers(client) -> dict[str, str]:
    email = f"other_{uuid.uuid4().hex}@example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": "password123"})
    login = await client.post(
        "/api/v1/auth/login", data={"username": email, "password": "password123"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


# --- authentication and status ------------------------------------------------


async def test_agent_routes_require_authentication(client):
    assert (await client.get("/api/v1/agent/status")).status_code == 401
    assert (await client.post("/api/v1/agent/chat", json={"messages": []})).status_code == 401


async def test_status_reports_an_unusable_backend_with_the_reason(
    client, auth_headers, unavailable_backend
):
    response = await client.get("/api/v1/agent/status", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["backend"] == "qwen"
    assert body["model"] == "Qwen/Qwen2.5-0.5B-Instruct"
    assert INSTALL_HINT in body["reason"]
    assert body["max_context_findings"] == settings.AGENT_MAX_CONTEXT_FINDINGS


async def test_status_of_the_real_configuration_matches_this_runtime(client, auth_headers):
    """With the model absent the default configuration must say so, not claim to work."""
    if missing_dependencies() is None:
        pytest.skip("transformers and torch are installed in this environment")

    body = (await client.get("/api/v1/agent/status", headers=auth_headers)).json()

    assert body["backend"] == "qwen"
    assert body["available"] is False
    assert INSTALL_HINT in body["reason"]


async def test_chat_without_the_model_is_a_503_that_names_the_missing_piece(
    client, auth_headers, unavailable_backend
):
    response = await client.post(
        "/api/v1/agent/chat",
        headers=auth_headers,
        json={"messages": [{"role": "user", "content": "Explain my findings"}]},
    )

    assert response.status_code == 503
    assert INSTALL_HINT in response.json()["detail"]


# --- ownership ---------------------------------------------------------------


async def test_a_project_from_another_user_is_forbidden(client, auth_headers, project, fake_backend):
    headers = await _second_user_headers(client)

    response = await client.post(
        "/api/v1/agent/chat",
        headers=headers,
        json={
            "messages": [{"role": "user", "content": "Explain my findings"}],
            "project_id": project["id"],
        },
    )

    assert response.status_code == 403
    assert fake_backend.calls == []


async def test_an_unknown_project_is_not_found(client, auth_headers, fake_backend):
    response = await client.post(
        "/api/v1/agent/chat",
        headers=auth_headers,
        json={
            "messages": [{"role": "user", "content": "Explain my findings"}],
            "project_id": str(uuid.uuid4()),
        },
    )

    assert response.status_code == 404


# --- request shape ------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"messages": []},
        {"messages": [{"role": "assistant", "content": "hi"}]},
        {"messages": [{"role": "user", "content": "   "}]},
        {"messages": [{"role": "user", "content": ""}]},
        {"messages": [{"role": "user", "content": "x" * (settings.AGENT_MAX_MESSAGE_CHARS + 1)}]},
        {
            "messages": [
                {"role": "user", "content": "hi"} for _ in range(settings.AGENT_MAX_MESSAGES + 1)
            ]
        },
    ],
)
async def test_chat_rejects_conversations_it_cannot_use(client, auth_headers, fake_backend, payload):
    response = await client.post("/api/v1/agent/chat", headers=auth_headers, json=payload)

    assert response.status_code == 422
    assert fake_backend.calls == []


# --- context and answer -------------------------------------------------------


async def test_chat_answers_with_the_findings_of_the_latest_finished_run(
    client, auth_headers, project, fake_backend
):
    run = await _completed_run(client, auth_headers, project["id"])
    total = run["summary"]["total_findings"]
    assert total > 0, "the demo sources must produce findings for this test to mean anything"

    response = await client.post(
        "/api/v1/agent/chat",
        headers=auth_headers,
        json={
            "messages": [{"role": "user", "content": "What should I fix first?"}],
            "project_id": project["id"],
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reply"] == fake_backend.answer
    assert body["backend"] == "fake"
    assert body["model"] == "fake-model"
    assert body["analysis_run_id"] == run["id"]
    assert body["findings_used"] == min(total, settings.AGENT_MAX_CONTEXT_FINDINGS)
    assert body["truncated"] is (total > settings.AGENT_MAX_CONTEXT_FINDINGS)

    system = fake_backend.calls[0][0].content
    assert "Findings included below:" in system
    quoted = (await client.get(f"/api/v1/analyses/{run['id']}/findings?limit=1", headers=auth_headers)).json()[0]
    assert f"{quoted['file_path']}:{quoted['line_start']}" in system
    assert quoted["tool"] in system


async def test_chat_can_be_scoped_to_one_run(client, auth_headers, project, fake_backend):
    run = await _completed_run(client, auth_headers, project["id"])

    body = (
        await client.post(
            "/api/v1/agent/chat",
            headers=auth_headers,
            json={
                "messages": [{"role": "user", "content": "Explain this run"}],
                "analysis_run_id": run["id"],
            },
        )
    ).json()

    assert body["analysis_run_id"] == run["id"]
    assert body["findings_used"] == min(
        run["summary"]["total_findings"], settings.AGENT_MAX_CONTEXT_FINDINGS
    )


async def test_chat_without_a_scope_quotes_nothing_and_says_so(client, auth_headers, fake_backend):
    response = await client.post(
        "/api/v1/agent/chat",
        headers=auth_headers,
        json={"messages": [{"role": "user", "content": "What is radon?"}]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["findings_used"] == 0
    assert body["analysis_run_id"] is None
    assert "No analysis is in scope" in fake_backend.calls[0][0].content


# --- rate limit ---------------------------------------------------------------


async def test_the_chat_is_rate_limited_per_user(client, auth_headers, fake_backend, monkeypatch):
    from app.core.ratelimit import agent_chat_limiter, reset_agent_chat_limiter

    monkeypatch.setattr(settings, "AGENT_RATE_LIMIT_PER_MINUTE", 1)
    reset_agent_chat_limiter()
    try:
        first = await client.post(
            "/api/v1/agent/chat",
            headers=auth_headers,
            json={"messages": [{"role": "user", "content": "one"}]},
        )
        second = await client.post(
            "/api/v1/agent/chat",
            headers=auth_headers,
            json={"messages": [{"role": "user", "content": "two"}]},
        )
    finally:
        reset_agent_chat_limiter()

    assert first.status_code == 200
    assert second.status_code == 429
    assert int(second.headers["retry-after"]) >= 1
