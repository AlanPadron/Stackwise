"""The streamed chat: the event sequence, the failure modes, and who can reach it.

The text is not the interesting part — it is the same answer the whole-answer
endpoint returns. What is pinned here is the transport: which events come out and
in what order, that a failure *before* the first byte is still a status code while
one *after* it can only be an event, and that a runtime which cannot stream still
produces a stream (one fragment) instead of breaking the caller.
"""

import json

import pytest

from app.agent.backend import AgentUnavailable, ChatMessage
from app.agent.service import AgentContext
from app.api.v1.agent import agent_backend
from app.core.config import settings
from app.main import app
from test_agent_api import _completed_run, _second_user_headers  # noqa: F401

STREAM_URL = "/api/v1/agent/chat/stream"
ANSWER = "B608 is a string-built SQL query; parameterise it."


class _StreamingBackend:
    """Streams a canned answer, optionally failing part-way through it."""

    name = "fake-stream"
    model = "fake-model"

    def __init__(self, *, fail_after: int | None = None, empty: bool = False) -> None:
        self.answer = "" if empty else ANSWER
        self.fail_after = fail_after
        self.calls: list[list[ChatMessage]] = []

    def unavailable_reason(self):
        return None

    async def complete(self, messages, *, max_new_tokens: int) -> str:
        self.calls.append(list(messages))
        return self.answer

    async def stream(self, messages, *, max_new_tokens: int):
        self.calls.append(list(messages))
        chunks = [self.answer[i : i + 7] for i in range(0, len(self.answer), 7)]
        for index, chunk in enumerate(chunks):
            if self.fail_after is not None and index == self.fail_after:
                raise AgentUnavailable(
                    "the model did not finish within 1 seconds"
                )
            yield chunk


class _WholeAnswerBackend:
    """A runtime that only speaks request/response: no `stream` attribute."""

    name = "fake-whole"
    model = "fake-model"

    def __init__(self) -> None:
        self.calls: list[list[ChatMessage]] = []

    def unavailable_reason(self):
        return None

    async def complete(self, messages, *, max_new_tokens: int) -> str:
        self.calls.append(list(messages))
        return ANSWER


def frames(body: str) -> list[tuple[str, dict]]:
    """The `(event, data)` pairs of a server-sent event body."""
    parsed: list[tuple[str, dict]] = []
    for block in body.split("\n\n"):
        event = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data += line[len("data:") :].strip()
        if event:
            parsed.append((event, json.loads(data) if data else {}))
    return parsed


def texts(parsed: list[tuple[str, dict]], event: str) -> list[str]:
    return [data.get("text", "") for name, data in parsed if name == event]


@pytest.fixture
def streaming_backend():
    def _install(backend=None):
        backend = backend or _StreamingBackend()
        app.dependency_overrides[agent_backend] = lambda: backend
        return backend

    yield _install
    app.dependency_overrides.pop(agent_backend, None)


async def _stream(client, headers, payload):
    """One streamed turn: the status and the parsed events."""
    async with client.stream("POST", STREAM_URL, headers=headers, json=payload) as response:
        body = (await response.aread()).decode("utf-8")
        status_code = response.status_code
        content_type = response.headers.get("content-type", "")
        cache_control = response.headers.get("cache-control", "")
    return status_code, content_type, cache_control, frames(body)


def payload(**overrides) -> dict:
    body = {"messages": [{"role": "user", "content": "What should I fix first?"}]}
    body.update(overrides)
    return body


# --- the event sequence -------------------------------------------------------


async def test_the_stream_reports_meta_then_fragments_then_the_whole_answer(
    client, auth_headers, streaming_backend
):
    streaming_backend()

    status_code, content_type, cache_control, parsed = await _stream(
        client, auth_headers, payload()
    )

    assert status_code == 200
    assert content_type.startswith("text/event-stream")
    assert cache_control == "no-store"

    names = [name for name, _ in parsed]
    assert names[0] == "meta"
    assert names[-1] == "done"
    assert set(names[1:-1]) == {"delta"}

    meta = parsed[0][1]
    assert meta["backend"] == "fake-stream"
    assert meta["model"] == "fake-model"
    assert meta["findings_used"] == 0
    assert meta["analysis_run_id"] is None

    assert "".join(texts(parsed, "delta")) == ANSWER
    assert parsed[-1][1]["reply"] == ANSWER


async def test_the_stream_quotes_the_findings_of_the_latest_finished_run(
    client, auth_headers, project, streaming_backend
):
    run = await _completed_run(client, auth_headers, project["id"])
    assert run["summary"]["total_findings"] > 0, "the demo sources must produce findings"
    backend = streaming_backend()

    _, _, _, parsed = await _stream(
        client, auth_headers, payload(project_id=project["id"])
    )

    assert parsed[-1][1]["reply"] == ANSWER
    assert parsed[0][1]["analysis_run_id"] == run["id"]
    assert parsed[0][1]["findings_used"] == min(
        run["summary"]["total_findings"], settings.AGENT_MAX_CONTEXT_FINDINGS
    )

    system = backend.calls[0][0].content
    finding = (
        await client.get(f"/api/v1/analyses/{run['id']}/findings?limit=1", headers=auth_headers)
    ).json()[0]
    assert "Findings included below:" in system
    assert f"{finding['file_path']}:{finding['line_start']}" in system


async def test_a_runtime_without_streaming_still_produces_a_stream(
    client, auth_headers, streaming_backend
):
    """One fragment, then the same ending: the caller never branches on the runtime."""
    streaming_backend(_WholeAnswerBackend())

    _, _, _, parsed = await _stream(client, auth_headers, payload())

    assert [name for name, _ in parsed] == ["meta", "delta", "done"]
    assert texts(parsed, "delta") == [ANSWER]
    assert parsed[-1][1]["reply"] == ANSWER


# --- failures before the first byte ------------------------------------------


async def test_a_conversation_the_agent_cannot_use_is_a_422_not_an_event(
    client, auth_headers, streaming_backend
):
    streaming_backend()

    response = await client.post(
        STREAM_URL,
        headers=auth_headers,
        json={"messages": [{"role": "assistant", "content": "I answer first"}]},
    )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/json")


async def test_an_unavailable_runtime_is_a_503_before_anything_is_streamed(
    client, auth_headers
):
    from app.agent.backend import UnavailableBackend

    app.dependency_overrides[agent_backend] = lambda: UnavailableBackend(
        name="cloudflare", model="@cf/qwen/qwen2.5-coder-32b-instruct", reason="no token"
    )
    try:
        response = await client.post(STREAM_URL, headers=auth_headers, json=payload())
    finally:
        app.dependency_overrides.pop(agent_backend, None)

    assert response.status_code == 503
    assert "no token" in response.json()["detail"]


async def test_a_project_from_another_user_is_forbidden_before_the_stream(
    client, auth_headers, project, streaming_backend
):
    backend = streaming_backend()
    headers = await _second_user_headers(client)

    response = await client.post(
        STREAM_URL, headers=headers, json=payload(project_id=project["id"])
    )

    assert response.status_code == 403
    assert backend.calls == []


async def test_the_stream_is_rate_limited_like_the_whole_answer_endpoint(
    client, auth_headers, streaming_backend, monkeypatch
):
    from app.core.ratelimit import reset_agent_chat_limiter

    monkeypatch.setattr(settings, "AGENT_RATE_LIMIT_PER_MINUTE", 1)
    reset_agent_chat_limiter()
    backend = streaming_backend()
    try:
        first = await client.post(STREAM_URL, headers=auth_headers, json=payload())
        second = await client.post(STREAM_URL, headers=auth_headers, json=payload())
    finally:
        reset_agent_chat_limiter()

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers["content-type"].startswith("application/json")
    assert len(backend.calls) == 1


async def test_both_chat_endpoints_require_a_session(client):
    assert (await client.post(STREAM_URL, json=payload())).status_code == 401


# --- failures inside the stream -----------------------------------------------


async def test_a_failure_mid_stream_keeps_the_fragments_and_reports_an_event(
    client, auth_headers, streaming_backend
):
    streaming_backend(_StreamingBackend(fail_after=2))

    status_code, _, _, parsed = await _stream(client, auth_headers, payload())

    assert status_code == 200  # the headers were sent long ago
    assert [name for name, _ in parsed] == ["meta", "delta", "delta", "error"]
    partial = "".join(texts(parsed, "delta"))
    assert partial and partial == ANSWER[:14]
    assert "did not finish" in parsed[-1][1]["detail"]


async def test_an_answer_with_no_text_is_an_error_not_an_empty_bubble(
    client, auth_headers, streaming_backend
):
    streaming_backend(_StreamingBackend(empty=True))

    _, _, _, parsed = await _stream(client, auth_headers, payload())

    assert [name for name, _ in parsed] == ["meta", "error"]
    assert "no text" in parsed[-1][1]["detail"]


async def test_the_stream_never_carries_a_secret(
    client, auth_headers, monkeypatch, streaming_backend
):
    """A backend that fails with a token in its message must not leak it."""
    secret = "cf-token-that-must-not-be-streamed"
    monkeypatch.setattr(settings, "CLOUDFLARE_API_TOKEN", secret)

    class _Leaky(_StreamingBackend):
        async def stream(self, messages, *, max_new_tokens: int):
            raise AgentUnavailable(f"rejected: {secret}")
            yield ""  # pragma: no cover - unreachable, this is an async generator

    streaming_backend(_Leaky())

    _, _, _, parsed = await _stream(client, auth_headers, payload())

    body = json.dumps(parsed)
    assert secret not in body
    assert parsed[-1][0] == "error"


# --- the service's own contract ----------------------------------------------


async def test_streaming_stops_when_the_budget_is_gone(client, auth_headers, streaming_backend, monkeypatch):
    """A model that keeps talking past the deadline is cut off, not waited on."""
    monkeypatch.setattr(settings, "AGENT_TIMEOUT_SECONDS", -1.0)
    streaming_backend()

    _, _, _, parsed = await _stream(client, auth_headers, payload())

    assert parsed[-1][0] == "error"
    assert "did not finish" in parsed[-1][1]["detail"]


def test_the_context_dataclass_is_immutable():
    """Both transports share it; neither may edit what the other quoted."""
    import dataclasses

    assert dataclasses.is_dataclass(AgentContext)
    with pytest.raises(dataclasses.FrozenInstanceError):
        AgentContext(
            conversation=[],
            findings_used=0,
            truncated=False,
            analysis_run_id=None,
            backend_name="x",
            model="y",
        ).findings_used = 3
