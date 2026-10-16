"""Cloudflare Workers AI: the wire format, the failures, and the secret.

`CloudflareBackend` is driven against a real HTTP server on a loopback port
instead of a mocked client, so what is asserted is the request httpx actually
writes — path, `Authorization` header, JSON body — and the answer it parses back.
The upstream payloads are Cloudflare's own, taken from its REST API docs; the
test never contacts Cloudflare and no real credential exists in this repository.

The properties worth pinning are the ones a reviewer would otherwise have to
take on trust: the token goes in a header and nowhere else, a failure is a
sanitised 503 rather than a raw upstream body, and an unconfigured or nonsensical
configuration is reported by setting name instead of failing per request.
"""

import contextlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.agent.backend import AgentUnavailable, ChatMessage
from app.agent.cloudflare import DEFAULT_MODEL_ID, CloudflareBackend
from app.agent.registry import resolve_backend
from app.api.v1.agent import agent_backend
from app.core.config import settings
from app.main import app

ACCOUNT_ID = "0123456789abcdef0123456789abcdef"
API_TOKEN = "cf-secret-token-that-must-never-be-echoed"
MODEL_ID = "@cf/qwen/qwen2.5-coder-32b-instruct"

#: Cloudflare's success envelope, verbatim from its REST API documentation.
SUCCESS = {
    "result": {"response": "B608 is a string-built SQL query; use parameters."},
    "success": True,
    "errors": [],
    "messages": [],
}


class _Stub(BaseHTTPRequestHandler):
    """Answers one canned scenario and records what it was asked."""

    def do_POST(self) -> None:  # noqa: N802 - http.server's naming
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        self.server.requests.append(
            {
                "path": self.path,
                "headers": {key.lower(): value for key, value in self.headers.items()},
                "body": json.loads(raw.decode("utf-8")) if raw else None,
            }
        )

        scenario = self.server.scenario
        if scenario.get("delay"):
            time.sleep(scenario["delay"])
        body = scenario.get("raw") or json.dumps(scenario.get("payload", {}))
        if isinstance(body, str):
            body = body.encode("utf-8")

        self.send_response(scenario.get("status", 200))
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        """Silence the server's stderr chatter."""


@contextlib.contextmanager
def stub_cloudflare(**scenario):
    """A loopback stand-in for `POST /accounts/{id}/ai/run/{model}`."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    server.scenario = scenario
    server.requests = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def backend_at(base_url: str, **overrides) -> CloudflareBackend:
    settings_ = {
        "account_id": ACCOUNT_ID,
        "api_token": API_TOKEN,
        "model_id": MODEL_ID,
        "temperature": 0.2,
        "timeout": 30.0,
        "base_url": base_url,
    }
    settings_.update(overrides)
    return CloudflareBackend(**settings_)


def conversation() -> list[ChatMessage]:
    return [
        ChatMessage(role="system", content="You are the Stackwise findings agent."),
        ChatMessage(role="user", content="¿Qué debería arreglar primero?"),
    ]


# --- configuration ------------------------------------------------------------


def test_the_settings_choose_a_cloudflare_backend(monkeypatch):
    monkeypatch.setattr(settings, "AGENT_BACKEND", "cloudflare")
    monkeypatch.setattr(settings, "CLOUDFLARE_ACCOUNT_ID", ACCOUNT_ID)
    monkeypatch.setattr(settings, "CLOUDFLARE_API_TOKEN", API_TOKEN)
    monkeypatch.setattr(settings, "CLOUDFLARE_MODEL_ID", MODEL_ID)

    backend = resolve_backend()

    assert isinstance(backend, CloudflareBackend)
    assert backend.name == "cloudflare"
    assert backend.model == MODEL_ID
    assert backend.unavailable_reason() is None
    assert DEFAULT_MODEL_ID == MODEL_ID


@pytest.mark.parametrize(
    "account_id, api_token, missing",
    [
        ("", API_TOKEN, "CLOUDFLARE_ACCOUNT_ID"),
        (ACCOUNT_ID, "", "CLOUDFLARE_API_TOKEN"),
        ("", "", "CLOUDFLARE_ACCOUNT_ID"),
    ],
)
def test_a_missing_setting_is_named_not_substituted(account_id, api_token, missing):
    backend = CloudflareBackend(account_id=account_id, api_token=api_token)

    reason = backend.unavailable_reason()

    assert reason is not None and missing in reason
    # A reason names settings; it must never carry a value.
    assert API_TOKEN not in reason


async def test_generating_without_configuration_raises_instead_of_calling_out():
    """An unconfigured backend must not attempt a request to a fixed default."""
    backend = CloudflareBackend(account_id="", api_token="")

    with pytest.raises(AgentUnavailable) as raised:
        await backend.complete(conversation(), max_new_tokens=64)

    assert "CLOUDFLARE_ACCOUNT_ID" in str(raised.value)


@pytest.mark.parametrize(
    "model_id",
    ["Qwen/Qwen2.5-0.5B-Instruct", "@cf/../../etc/passwd", "@cf/qwen/x y", "cf/qwen/model"],
)
def test_a_model_id_that_is_not_a_catalogue_id_is_refused(model_id):
    """The id is interpolated into the request path, so only the real shape passes."""
    backend = CloudflareBackend(account_id=ACCOUNT_ID, api_token=API_TOKEN, model_id=model_id)

    reason = backend.unavailable_reason()

    assert reason is not None and "CLOUDFLARE_MODEL_ID" in reason


async def test_an_invalid_model_id_never_reaches_the_network():
    """A path-traversal attempt in the setting must not produce a request at all."""
    backend = backend_at("http://127.0.0.1:1", model_id="@cf/../../etc/passwd")

    with pytest.raises(AgentUnavailable) as raised:
        await backend.complete(conversation(), max_new_tokens=32)

    assert "CLOUDFLARE_MODEL_ID" in str(raised.value)


def test_a_two_segment_catalogue_id_is_accepted():
    """`@cf/<model>` is a real shape (Cloudflare-authored models), not a typo."""
    backend = CloudflareBackend(account_id=ACCOUNT_ID, api_token=API_TOKEN, model_id="@cf/qwen")

    assert backend.unavailable_reason() is None
    assert backend._endpoint() == f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/qwen"


def test_an_empty_model_id_falls_back_to_the_reference_model():
    """An operator who blanks the setting gets the documented default, not a 503."""
    backend = CloudflareBackend(account_id=ACCOUNT_ID, api_token=API_TOKEN, model_id="")

    assert backend.unavailable_reason() is None
    assert backend.model == DEFAULT_MODEL_ID


# --- the request --------------------------------------------------------------


async def test_the_request_carries_the_model_the_token_and_the_conversation():
    with stub_cloudflare(payload=SUCCESS) as (base_url, server):
        answer = await backend_at(base_url).complete(conversation(), max_new_tokens=64)

    assert answer == SUCCESS["result"]["response"]

    sent = server.requests[0]
    assert sent["path"] == f"/accounts/{ACCOUNT_ID}/ai/run/{MODEL_ID}"
    assert sent["headers"]["authorization"] == f"Bearer {API_TOKEN}"
    assert sent["body"]["messages"] == [
        {"role": "system", "content": "You are the Stackwise findings agent."},
        {"role": "user", "content": "¿Qué debería arreglar primero?"},
    ]
    assert sent["body"]["max_tokens"] == 64
    assert sent["body"]["temperature"] == 0.2


async def test_the_token_travels_only_in_the_authorization_header():
    """The body and the query string are logged by proxies; the header is not."""
    with stub_cloudflare(payload=SUCCESS) as (base_url, server):
        await backend_at(base_url).complete(conversation(), max_new_tokens=32)

    sent = server.requests[0]
    assert sent["headers"]["authorization"] == f"Bearer {API_TOKEN}"
    assert API_TOKEN not in sent["path"]
    assert API_TOKEN not in json.dumps(sent["body"])


# --- failures are sanitised ---------------------------------------------------


async def test_rejected_credentials_name_the_setting_not_the_token():
    with stub_cloudflare(
        status=401,
        payload={
            "result": None,
            "success": False,
            "errors": [{"code": 10000, "message": f"Authentication error for {API_TOKEN}"}],
        },
    ) as (base_url, _):
        with pytest.raises(AgentUnavailable) as raised:
            await backend_at(base_url).complete(conversation(), max_new_tokens=32)

    detail = str(raised.value)
    assert "CLOUDFLARE_API_TOKEN" in detail
    assert API_TOKEN not in detail


async def test_a_rate_limit_is_reported_as_such():
    with stub_cloudflare(status=429, payload={"success": False, "errors": []}) as (base_url, _):
        with pytest.raises(AgentUnavailable) as raised:
            await backend_at(base_url).complete(conversation(), max_new_tokens=32)

    assert "rate limiting" in str(raised.value)


async def test_an_upstream_refusal_quotes_cloudflares_own_message():
    with stub_cloudflare(
        status=400,
        payload={
            "result": None,
            "success": False,
            "errors": [{"code": 7000, "message": "No route for that model"}],
            "messages": [],
        },
    ) as (base_url, _):
        with pytest.raises(AgentUnavailable) as raised:
            await backend_at(base_url).complete(conversation(), max_new_tokens=32)

    assert "No route for that model" in str(raised.value)


async def test_an_error_body_that_repeats_the_token_is_scrubbed():
    with stub_cloudflare(
        status=500,
        raw=f"upstream exploded with Authorization: Bearer {API_TOKEN}",
    ) as (base_url, _):
        with pytest.raises(AgentUnavailable) as raised:
            await backend_at(base_url).complete(conversation(), max_new_tokens=32)

    detail = str(raised.value)
    assert "HTTP 500" in detail
    assert API_TOKEN not in detail
    assert "<redacted>" in detail


async def test_a_refusal_flagged_in_the_envelope_is_not_read_as_an_answer():
    """`success: false` with HTTP 200 must not become the model's text."""
    with stub_cloudflare(
        payload={
            "result": {"response": "should not be returned"},
            "success": False,
            "errors": [{"code": 5007, "message": "Account is out of credits"}],
        }
    ) as (base_url, _):
        with pytest.raises(AgentUnavailable) as raised:
            await backend_at(base_url).complete(conversation(), max_new_tokens=32)

    assert "Account is out of credits" in str(raised.value)


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"success": True, "result": {"response": "   "}}, "no text"),
        ({"success": True, "result": {}}, "no text"),
        ({"success": True}, "no text"),
        ({"result": {"response": "hi"}}, "refused"),
    ],
)
async def test_an_unexpected_payload_becomes_a_sanitised_failure(payload, expected):
    with stub_cloudflare(payload=payload) as (base_url, _):
        with pytest.raises(AgentUnavailable) as raised:
            await backend_at(base_url).complete(conversation(), max_new_tokens=32)

    assert expected in str(raised.value)


async def test_a_non_json_response_is_reported_as_such():
    with stub_cloudflare(raw="<html>gateway error</html>") as (base_url, _):
        with pytest.raises(AgentUnavailable) as raised:
            await backend_at(base_url).complete(conversation(), max_new_tokens=32)

    assert "not JSON" in str(raised.value)


async def test_a_timeout_becomes_an_unavailable_backend():
    with stub_cloudflare(payload=SUCCESS, delay=1.0) as (base_url, _):
        with pytest.raises(AgentUnavailable) as raised:
            await backend_at(base_url, timeout=0.1).complete(conversation(), max_new_tokens=32)

    assert "could not be reached" in str(raised.value)


async def test_an_unreachable_host_becomes_an_unavailable_backend():
    # Port 0 is never listening: a real connection error, not a mocked one.
    backend = backend_at("http://127.0.0.1:1", timeout=2.0)

    with pytest.raises(AgentUnavailable) as raised:
        await backend.complete(conversation(), max_new_tokens=32)

    detail = str(raised.value)
    assert "could not be reached" in detail
    assert API_TOKEN not in detail


# --- the endpoints ------------------------------------------------------------


async def test_status_reports_cloudflare_when_the_settings_are_complete(
    client, auth_headers, monkeypatch
):
    monkeypatch.setattr(settings, "AGENT_BACKEND", "cloudflare")
    monkeypatch.setattr(settings, "CLOUDFLARE_ACCOUNT_ID", ACCOUNT_ID)
    monkeypatch.setattr(settings, "CLOUDFLARE_API_TOKEN", API_TOKEN)
    monkeypatch.setattr(settings, "CLOUDFLARE_MODEL_ID", MODEL_ID)

    body = (await client.get("/api/v1/agent/status", headers=auth_headers)).json()

    assert body["available"] is True
    assert body["backend"] == "cloudflare"
    assert body["model"] == MODEL_ID
    assert body["reason"] is None


async def test_an_unconfigured_cloudflare_is_a_503_that_names_the_settings(
    client, auth_headers, monkeypatch
):
    monkeypatch.setattr(settings, "AGENT_BACKEND", "cloudflare")
    monkeypatch.setattr(settings, "CLOUDFLARE_ACCOUNT_ID", "")
    monkeypatch.setattr(settings, "CLOUDFLARE_API_TOKEN", "")

    status = (await client.get("/api/v1/agent/status", headers=auth_headers)).json()
    assert status["available"] is False
    assert "CLOUDFLARE_ACCOUNT_ID" in status["reason"]

    chat = await client.post(
        "/api/v1/agent/chat",
        headers=auth_headers,
        json={"messages": [{"role": "user", "content": "Explain my findings"}]},
    )

    assert chat.status_code == 503
    assert "CLOUDFLARE_API_TOKEN" in chat.json()["detail"]


async def test_chat_answers_through_the_hosted_backend(client, auth_headers):
    """End to end: request → HTTP → Workers AI payload → response body."""
    with stub_cloudflare(payload=SUCCESS) as (base_url, server):
        app.dependency_overrides[agent_backend] = lambda: backend_at(base_url)
        try:
            response = await client.post(
                "/api/v1/agent/chat",
                headers=auth_headers,
                json={"messages": [{"role": "user", "content": "¿Qué arreglo primero?"}]},
            )
        finally:
            app.dependency_overrides.pop(agent_backend, None)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reply"] == SUCCESS["result"]["response"]
    assert body["backend"] == "cloudflare"
    assert body["model"] == MODEL_ID
    assert body["findings_used"] == 0

    sent = server.requests[0]
    assert sent["path"] == f"/accounts/{ACCOUNT_ID}/ai/run/{MODEL_ID}"
    assert [message["role"] for message in sent["body"]["messages"]] == ["system", "user"]
    assert sent["body"]["max_tokens"] == settings.AGENT_MAX_NEW_TOKENS
