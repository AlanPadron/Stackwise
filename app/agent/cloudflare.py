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

import re
from typing import Any, Optional, Sequence
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

#: Workers AI model ids look like `@cf/vendor/model-name` (LoRA variants add a
#: segment). Validated rather than trusted: the id is interpolated into the path
#: of the outbound request, so nothing else may look like a model id.
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

        payload: dict[str, Any] = {
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
            "max_tokens": max_new_tokens,
            "temperature": self._temperature,
        }
        headers = {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    self._endpoint(), json=payload, headers=headers
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

    def _endpoint(self) -> str:
        """The one URL this backend ever posts to.

        The account id is 32 hex characters and the model id was validated to the
        catalogue shape, so neither can add a path segment of its own. The model
        keeps its slashes — that is how Cloudflare writes the route.

        Raises rather than returning a doubtful URL: this is the last point
        before the request exists.
        """
        error = self._model_id_error()
        if error is not None:
            raise AgentUnavailable(error)
        return self._base_url + _RUN_PATH.format(
            account=quote(self._account_id, safe=""),
            model=quote(self.model, safe="@/.-_"),
        )

    def _answer(self, response: httpx.Response) -> str:
        """The model's text, or `AgentUnavailable` with a sanitised reason."""
        if response.status_code in (401, 403):
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
