"""Cloudflare Workers AI, over its REST API.

The hosted counterpart to `qwen.py`: nothing is installed, no checkpoint is
downloaded and no GPU is needed — one HTTPS call to Cloudflare's `/ai/run`
endpoint per turn. That is what a serverless bundle, a container with a small
image, or any host without spare RAM can actually run.

The API token is a backend secret. It is read from `CLOUDFLARE_API_TOKEN`, sent
only in the `Authorization` header, and never echoed back: every failure this
module raises carries a *sanitised*, bounded reason, and the response body is
scrubbed of the token before any of it is quoted.

Endpoint shape (verified against the live API up to authentication — an
unauthenticated POST returns Cloudflare's own `{"success": false, "errors":
[{"code": 10000, "message": "Authentication error"}]}` envelope with HTTP 401):

    POST {base}/accounts/{account_id}/ai/run/{model}
    Authorization: Bearer <token>
    {"messages": [{"role", "content"}, ...], "max_tokens": N, "temperature": T}

    → {"result": {"response": "..."}, "success": true, "errors": [], ...}
"""

import json
import re
from typing import Any, AsyncIterator, Optional, Sequence
from urllib.parse import quote

import httpx

from app.agent.backend import AgentUnavailable, ChatMessage
from app.analysis.redact import redact

#: Model id exactly as Cloudflare catalogues it (32k context, billed per token).
DEFAULT_MODEL_ID = "@cf/qwen/qwen2.5-coder-32b-instruct"

#: Fixed origin. Account and model travel in the path, the token in a header, so
#: the only variable part of the target is validated configuration rather than a
#: URL a caller could steer.
API_BASE_URL = "https://api.cloudflare.com/client/v4"

_RUN_PATH = "/accounts/{account}/ai/run/{model}"

#: A Cloudflare account id. It is 32 hex characters in practice, but it is
#: validated as one URL-safe path segment rather than as that exact shape, so a
#: future format still works. `.` is deliberately excluded: it survives
#: percent-encoding, so `..` would climb out of the `/accounts/<id>/` segment the
#: id is interpolated into.
_ACCOUNT_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

#: Workers AI model ids look like `@cf/vendor/model-name` (LoRA variants add a
#: segment). Validated rather than trusted for the same reason: the id is
#: interpolated into the path of the outbound request, so nothing else may look
#: like a model id, and `.` (in `quote`'s always-safe set) is why the `..` check
#: below is separate.
_MODEL_ID = re.compile(r"^@[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+$")

#: Longest slice of an upstream error body we are willing to quote.
_ERROR_CHARS = 200


class CloudflareBackend:
    """Runs a hosted Workers AI chat model, one generation per request."""

    name = "cloudflare"

    def __init__(
        self,
        *,
        account_id: str,
        api_token: str,
        model_id: str = DEFAULT_MODEL_ID,
        temperature: float = 0.2,
        timeout: float = 60.0,
        base_url: str = API_BASE_URL,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        # `model` is part of the protocol: the API reports it so an operator can
        # see which checkpoint answered. The path never carries weights.
        self.model = (model_id or "").strip() or DEFAULT_MODEL_ID
        self._account_id = (account_id or "").strip()
        self._api_token = (api_token or "").strip()
        self._temperature = temperature
        self._timeout = timeout
        self._base_url = base_url.rstrip("/")
        # Injectable so a test can drive the real request path without a socket.
        self._transport = transport

    # --- availability -----------------------------------------------------

    def unavailable_reason(self) -> Optional[str]:
        """Which settings are missing, by name — never by value."""
        missing = [
            name
            for name, value in (
                ("CLOUDFLARE_ACCOUNT_ID", self._account_id),
                ("CLOUDFLARE_API_TOKEN", self._api_token),
            )
            if not value
        ]
        if missing:
            return (
                "the Cloudflare Workers AI backend is not configured: set "
                + " and ".join(missing)
                + " in the API environment and restart the API"
            )
        return self._settings_error()

    def _settings_error(self) -> Optional[str]:
        """The first malformed setting, by name — never by value.

        A value that is present but wrong is the misconfiguration an operator is
        most likely to make (an account e-mail or a dashboard URL pasted into
        `CLOUDFLARE_ACCOUNT_ID`), and the upstream answer to that is an
        unhelpful 404 far from its cause.
        """
        if not _ACCOUNT_ID.match(self._account_id):
            return (
                "CLOUDFLARE_ACCOUNT_ID is not a Cloudflare account id: expected the "
                "32-character id from the dashboard, not an e-mail address or a URL"
            )
        return self._model_id_error()

    def _model_id_error(self) -> Optional[str]:
        """The model id in the catalogue shape, or why it is not.

        Not pedantry: the id is interpolated into the path of the outbound
        request, so `@cf/../../…` would steer that request elsewhere. `.` is in
        `urllib.parse.quote`'s always-safe set, so the guard has to be here
        rather than in the quoting.
        """
        if _MODEL_ID.match(self.model) and ".." not in self.model:
            return None
        return (
            f"CLOUDFLARE_MODEL_ID is not a Workers AI model id: '{self.model}' "
            "(expected the catalogue form, e.g. @cf/qwen/qwen2.5-coder-32b-instruct)"
        )

    # --- generation -------------------------------------------------------

    async def complete(
        self, messages: Sequence[ChatMessage], *, max_new_tokens: int
    ) -> str:
        reason = self.unavailable_reason()
        if reason is not None:
            raise AgentUnavailable(reason)

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    self._endpoint(),
                    json=self._payload(messages, max_new_tokens),
                    headers=self._headers(),
                )
        except httpx.HTTPError as exc:
            # The exception's own text can carry the URL, never the header; the
            # class name is enough for an operator to tell a timeout from a DNS
            # failure, and nothing from the request is quoted.
            raise AgentUnavailable(
                "Cloudflare Workers AI could not be reached "
                f"({type(exc).__name__})"
            ) from None

        return self._answer(response)

    def _payload(
        self, messages: Sequence[ChatMessage], max_new_tokens: int, *, stream: bool = False
    ) -> dict[str, Any]:
        """The request body both call shapes share."""
        payload: dict[str, Any] = {
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "max_tokens": max_new_tokens,
            "temperature": self._temperature,
        }
        if stream:
            payload["stream"] = True
        return payload

    def _headers(self, *, stream: bool = False) -> dict[str, str]:
        """`Authorization` is the only place the token ever appears."""
        headers = {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
        }
        if stream:
            headers["Accept"] = "text/event-stream"
        return headers

    async def stream(
        self, messages: Sequence[ChatMessage], *, max_new_tokens: int
    ) -> AsyncIterator[str]:
        """The answer in fragments, from Cloudflare's event stream.

        The same request as `complete()` with `"stream": true`, which switches the
        response to `text/event-stream`; each frame is `data: {"response": "…"}`
        and the last one is `data: [DONE]` (Cloudflare's own documented shape).
        Frames that carry no text — comments, keep-alives, anything unparsable —
        are skipped rather than treated as failures, so a surprise in the stream
        costs a fragment, not the answer.

        Closing the generator closes the connection, so a client that gives up
        cancels the upstream generation too.
        """
        reason = self.unavailable_reason()
        if reason is not None:
            raise AgentUnavailable(reason)

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                async with client.stream(
                    "POST",
                    self._endpoint(),
                    json=self._payload(messages, max_new_tokens, stream=True),
                    headers=self._headers(stream=True),
                ) as response:
                    if response.status_code >= 400:
                        # The failure is a JSON envelope, not a stream: read it so
                        # the sanitised reason matches the non-streaming path.
                        await response.aread()
                        self._check_status(response)
                        raise AgentUnavailable(
                            "Cloudflare Workers AI refused to stream this request"
                        )

                    async for delta in self._frames(response):
                        yield delta
        except httpx.HTTPError as exc:
            raise AgentUnavailable(
                "Cloudflare Workers AI could not be reached "
                f"({type(exc).__name__})"
            ) from None

    async def _frames(self, response: httpx.Response) -> AsyncIterator[str]:
        """The text carried by each server-sent event of a stream."""
        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                continue
            try:
                frame = json.loads(data)
            except ValueError:
                continue
            text = frame.get("response") if isinstance(frame, dict) else None
            if isinstance(text, str) and text:
                yield text

    def _endpoint(self) -> str:
        """The one URL this backend ever posts to.

        Both interpolated values are the validated settings: the account id is
        one URL-safe segment (no `.`, so no `..`) and the model id is the
        catalogue shape, which keeps its slashes because that is how Cloudflare
        writes the route.

        Raises rather than returning a doubtful URL: this is the last point
        before the request exists.
        """
        error = self._settings_error()
        if error is not None:
            raise AgentUnavailable(error)
        return self._base_url + _RUN_PATH.format(
            account=quote(self._account_id, safe=""),
            model=quote(self.model, safe="@/.-_"),
        )

    def _answer(self, response: httpx.Response) -> str:
        """The model's text, or `AgentUnavailable` with a sanitised reason."""
        self._check_status(response)

        try:
            body = response.json()
        except ValueError:
            raise AgentUnavailable(
                "Cloudflare Workers AI returned a response that was not JSON"
            ) from None
        if not isinstance(body, dict):
            raise AgentUnavailable(
                "Cloudflare Workers AI returned an unexpected response shape"
            )

        if not body.get("success"):
            raise AgentUnavailable(
                "Cloudflare Workers AI refused the request"
                f"{self._errors(body)}"
            )

        result = body.get("result")
        answer = result.get("response") if isinstance(result, dict) else None
        if not isinstance(answer, str) or not answer.strip():
            raise AgentUnavailable(
                "Cloudflare Workers AI returned no text for this request"
            )
        return answer

    def _check_status(self, response: httpx.Response) -> None:
        """Raise the sanitised reason for a failed response; return on success.

        Shared by the two call shapes: the whole-answer request reads the body
        before calling this, a streamed one has to read it first because the
        body is the event stream.
        """
        if response.status_code == 401 or response.status_code == 403:
            # Never quote the body here: this is the one branch an operator could
            # hit with a malformed token still in hand.
            raise AgentUnavailable(
                "Cloudflare Workers AI rejected the credentials: check "
                "CLOUDFLARE_API_TOKEN (it needs the `Workers AI - Read` permission)"
            )
        if response.status_code == 429:
            raise AgentUnavailable(
                "Cloudflare Workers AI is rate limiting this account; try again shortly"
            )
        if response.status_code >= 400:
            raise AgentUnavailable(
                f"Cloudflare Workers AI answered HTTP {response.status_code}"
                f"{self._detail(response)}"
            )

    def _detail(self, response: httpx.Response) -> str:
        text = self._sanitize(response.text)
        return f": {text}" if text else ""

    def _errors(self, body: dict[str, Any]) -> str:
        """Cloudflare's `errors[]` as one bounded, sanitised line."""
        errors = body.get("errors")
        if not isinstance(errors, list):
            return ""
        messages = [
            error.get("message")
            for error in errors
            if isinstance(error, dict) and isinstance(error.get("message"), str)
        ]
        joined = self._sanitize("; ".join(messages))
        return f": {joined}" if joined else ""

    def _sanitize(self, text: str) -> str:
        """Strip the token, then anything else secret-shaped, then bound it.

        Belt and braces: the token is removed verbatim first (it has no prefix
        for `redact()` to recognise), and `redact()` still runs so a credential
        Cloudflare chose to quote back would be caught too.
        """
        if self._api_token:
            text = text.replace(self._api_token, "<redacted>")
        return redact(text, limit=_ERROR_CHARS).strip()
