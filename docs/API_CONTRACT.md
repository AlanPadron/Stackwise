# API Contract - Stackwise V1

Base path `/api/v1`. Full engine documentation: [ANALYSIS_ENGINE.md](ANALYSIS_ENGINE.md).

## 1. Authentication

- `POST /auth/register`: Create a new account.
  - Request: `{ "email": "user@example.com", "password": "securepassword123" }`
  - Password policy (`app/core/security.py`, not configurable): 10+ characters, at least one letter
    and one digit, at most 72 bytes, not built on a common base. `422` with the reason otherwise.
  - The address is stored lowercased, so `User@x.com` and `user@x.com` are the same account.
  - `400` when the address already has an account; `429` (+ `Retry-After`) when one client address
    registers more than `AUTH_REGISTER_RATE_LIMIT_PER_MINUTE` accounts in a minute.
  - Response: `201 Created` with User object.
- `POST /auth/login`: Get JWT token.
  - Request: (Form Data) `username` (email), `password`.
  - `401` for an unknown address *and* for a wrong password: same status, same body, and the same
    bcrypt work (an unknown address is checked against a dummy hash), so it enumerates nothing.
  - `429` (+ `Retry-After`) once attempts exceed `AUTH_LOGIN_RATE_LIMIT_PER_MINUTE` — counted per
    account and per client address in one atomic check.
  - Response: `200 OK` with `{ "access_token": "...", "token_type": "bearer" }`.
- `GET /auth/me`: Get current user profile.
  - Header: `Authorization: Bearer <token>`
  - Response: `200 OK` with User object.

### OAuth sign-in (Google, GitHub)

Both providers are plain authorization-code flows, and neither needs code to be switched on: the API
reads a client id/secret pair, and a provider whose pair is empty is reported as unavailable by
`/auth/providers` (its button is then hidden by the SPA). To turn them on:

1. **Google** — <https://console.cloud.google.com/apis/credentials> → *Create credentials* → *OAuth
   client ID* → *Web application*. Add the authorized redirect URI
   `$API_PUBLIC_URL/api/v1/auth/oauth/google/callback` **verbatim** (default
   `http://localhost:8001/api/v1/auth/oauth/google/callback`), then set `GOOGLE_CLIENT_ID` and
   `GOOGLE_CLIENT_SECRET`.
2. **GitHub** — <https://github.com/settings/developers> → *New OAuth App*. Same callback URL shape
   with `github` in place of `google`, then `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET`. The flow
   also requests `repo`, which is what makes private repositories importable; a user who declines it
   can still sign in and still import public repositories.
3. Restart the API and reload the SPA: the buttons appear from `GET /auth/providers`, with no
   frontend change and no rebuild.

Before any of that exists, `DEV_OAUTH_MOCK=true` serves the same round-trip from this API (a consent
screen plus a fixed `example.com` identity), so the whole flow — start, consent, callback, session in
the URL fragment — can be exercised and tested locally. It must never be enabled on a reachable host.

- `GET /auth/providers`: Which providers this server can offer.
  - Response: `200 OK` with `{ "google": true, "github": false, "mock": false }`.
- `GET /auth/oauth/{provider}/authorize`: Start the round-trip.
  - Query: `next` (optional SPA path to land on).
  - Header: `Authorization: Bearer <token>` *optional* — when present the provider account is
    **linked** to the caller instead of signing in.
  - Response: `200 OK` with `{ "authorization_url": "..." }`; `404` unknown provider, `503` not
    configured on this server. Also sets the PKCE verifier cookie (`sw_oauth_pkce`, HttpOnly, scoped to
    `/api/v1/auth/oauth`).
- `GET /auth/oauth/{provider}/callback`: Provider redirect target (not called by the SPA).
  - Query: `code`, `state` (signed), or `error` when the provider refused.
  - Response: `302` to `<FRONTEND_URL>/auth/callback#token=<jwt>&next=<path>`, or
    `#error=state|pkce|provider|link|denied` when it fails. `pkce` means the code arrived in a browser
    that did not start the flow (no verifier cookie, or one that does not match the challenge).
- `GET /auth/oauth/links`: Provider identities attached to the caller's account.
  - Header: `Authorization: Bearer <token>`
  - Response: `200 OK` with `[ { "provider": "github", "login": "octocat", "email": "...",
    "created_at": "..." } ]` — the provider access token is never included.
- `DELETE /auth/oauth/links/{provider}`: Detach one identity, revoking its token at the provider.
  - Response: `204`; `404` unknown provider or nothing linked; `409` when it is the account's **only**
    way in (an OAuth-only account has no password to fall back on).

### GitHub repositories

- `GET /github/repositories`: Repositories the caller's linked GitHub account can read.
  - Response: `200 OK` with `{ "connected": true, "login": "octocat", "repositories": [ { "full_name": "octocat/hello-world", ... } ] }`
  - `connected: false` (with an empty list) means no GitHub account is linked yet.
  - `502` when GitHub rejects the stored token or the configured base URL fails the SSRF guard.

## 2. Project management

A project exists only with a GitHub repository behind it, so importing a repository is the one way to
create one — there is no manual project creation.

- `POST /projects/from-repo`: Create a project from a GitHub repository and start its first run.
  - Request: `{ "repository": "owner/name", "ref": "main", "name": "optional", "description": "optional", "analysis_config": { ... } }`
  - Response: `201 Created` with `{ "project": {...}, "run": {...} }` (the run is `pending` and
    executes in the background).
  - `409` when no GitHub account is linked; `404` when the repository is not accessible; `422` when
    the repository/ref/config is malformed; `502` when GitHub fails, the archive exceeds
    `ANALYSIS_MAX_ARCHIVE_SIZE_MB`, or the configured GitHub base URL is refused.
- `GET /projects`: List the caller's projects.
- `GET /projects/{id}`, `PATCH /projects/{id}`, `DELETE /projects/{id}`: read / update / delete.
  `PATCH` validates `analysis_config` against the platform ceiling (`422` if it would widen a limit).

## 3. Analysis engine

A run is started by `POST /projects/from-repo`, the same call that creates its project; the routes
below read runs and findings, they do not start anything.

- `GET /projects/{id}/analyses`: Run history, newest first.
  - Query: `limit` (default 50, max 200), `offset`, `status`
    (`pending|running|completed|completed_with_errors|failed|cancelled`; the legacy `processing` is
    accepted), `source_type` (`github`; the legacy `zip` value is still accepted as a filter, but every
    run the app can create today is `github`).
  - Response: `200 OK` with an array of AnalysisRun objects and an `X-Total-Count` header.
- `GET /analyses/{id}`: Status, summary, metrics and risk of one run. Also reaps runs abandoned by a
  dead worker (`failed`, `error_category: "stale_run"`).
  - Response: `200 OK` with the AnalysisRun object:
    `{ id, project_id, status, source_type, source_ref, source_hash, engine_version, config_version,
       config_hash, analysis_config, started_at, finished_at, duration_seconds, error_category,
       error_message, summary, metrics, risk, tool_versions, created_at }`
- `GET /analyses/{id}/findings`: Normalized findings of a run.
  - Query: `limit` (default 50, max 200), `offset`, `severity`
    (`critical|high|medium|low|info`), `category` (`security|bug|complexity|maintainability|style|
    dead_code|performance|other`), `tool` (`ruff|bandit|radon`), `rule_id`, `file_path`
    (repository-relative), `sort` (`severity|file|-created_at`).
  - Response: `200 OK` with an array of Finding objects and an `X-Total-Count` header.
- `GET /findings/{id}`: One finding by id (ownership checked: `403` for another user's project).
  - Response: `200 OK` with
    `{ id, analysis_run_id, project_id, tool, rule_id, category, severity, confidence, title,
       message, file_path, line_start, line_end, column_start, column_end, fingerprint, references,
       finding_metadata, created_at }`

Severity, category, tool, status, sort and numeric page arguments are validated: an unsupported
value is a `422`, never a silently empty page.

## 4. Health

- `GET /health`: unauthenticated liveness probe outside `/api/v1` —
  `{ "status": "healthy", "version": "...", "engine_version": "..." }`. Answers even when the
  database is down.
- `GET /api/v1/health`: readiness — `{ "status": "ok"|"degraded", "version": "...",
  "engine_version": "...", "database": "ok"|"unavailable" }`. Never returns a connection string,
  driver error or stack trace.

Both health responses, every error response and every finding are free of application secrets: the
API redacts anything secret-shaped before it is stored or returned, and a database failure is a
`503 {"detail": "The database is unavailable"}` with the driver's message kept in the log.

## 5. Dashboard

- `GET /dashboard/summary`: High-level counters.
  - Response: `200 OK` with `{ "total_projects": 5, "total_analyses": 10, "completed_analyses": 8,
    "total_findings": 42, "findings_by_severity": { "critical": 0, "high": 2, "medium": 10,
    "low": 30, "info": 0 }, "last_analysis_status": "completed" }`
  - `completed_analyses` counts both `completed` and `completed_with_errors` runs.

## 6. Findings agent

The chat that explains findings (see the analysis engine doc for how findings are produced). It is
not a second source of truth: every answer is generated from the findings in scope, and the model
that writes it is reported alongside the text.

- `GET /agent/status`: Whether the chat can answer, and what it is configured to run.
  - Response: `200 OK` with
    `{ "available": true, "backend": "cloudflare", "model": "@cf/qwen/qwen2.5-coder-32b-instruct",
       "reason": null, "max_context_findings": 60, "max_message_chars": 4000 }`
  - `available: false` carries a `reason` naming the *setting* that is missing or the package that
    is not installed — never a value, a path or a secret. `backend` is `qwen`, `cloudflare` or
    `none` (`AGENT_BACKEND`).
- `POST /agent/chat`: Answer the last turn with the findings in scope as context.
  - Request:
    `{ "messages": [ { "role": "user", "content": "..." } ], "project_id": "...", "analysis_run_id": "..." }`
    — `project_id` and `analysis_run_id` are optional (both are ownership-checked; `403` for
    another user's, `404` for an unknown one). Without them the agent has no findings to quote and
    says so.
  - Response: `200 OK` with
    `{ "reply": "...", "backend": "cloudflare", "model": "...", "findings_used": 12,
       "truncated": false, "analysis_run_id": "..." }`
  - Errors: `422` for a conversation it cannot use (empty, no final `user` turn, blank content,
    more than `AGENT_MAX_MESSAGES` turns, a message longer than `AGENT_MAX_MESSAGE_CHARS`);
    `429` rate limit (`AGENT_RATE_LIMIT_PER_MINUTE` per user per worker process); `503` when the
    configured backend cannot run, with the sanitised reason as `detail` — never an invented
    explanation.
- `POST /agent/chat/stream`: the same answer, as it is written.
  - Request: identical to `POST /agent/chat`.
  - Response: `200 OK`, `Content-Type: text/event-stream`, `Cache-Control: no-store`. Events, in
    order:
    - `event: meta` — `{ "backend": "cloudflare", "model": "...", "findings_used": 12,
      "truncated": false, "analysis_run_id": "..." }`, sent before the model is asked anything.
    - `event: delta` — `{ "text": "…" }`, repeated. A fragment is emitted as the runtime produces it;
      a runtime that cannot stream sends exactly one.
    - `event: done` — `{ "reply": "…" }`, the complete answer (the concatenation of the fragments).
    - `event: error` — `{ "detail": "…" }`, sanitised, replacing `done` when generation failed. The
      fragments already sent are kept by the client.
  - Errors: `422` / `429` / `503` / `403` / `404` exactly as above, and — because they happen before
    the first byte — they are ordinary JSON responses with a status code. A failure after that can
    only be announced as an `error` event.
  - Closing the connection aborts the upstream generation.

## 7. Secrets

Every response listed above is free of application secrets, and the same holds for the findings
agent: `CLOUDFLARE_API_TOKEN` is read only by the API process, sent only in the `Authorization`
header of the outbound Workers AI request, and scrubbed from any upstream error text before it can
reach a response or a log.
