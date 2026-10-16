"""Runtime configuration, read from environment variables / `.env`.

`SECRET_KEY` has no default on purpose: the app refuses to start rather than run
with an insecure key. See `.env.example` for the full set.

The `ANALYSIS_*` block is the *platform ceiling* for the analysis engine: a
project-level analysis configuration (see `app/analysis/config.py`) may only
narrow these values, never widen them. Keep that rule when adding a setting.
"""

from pydantic_settings import BaseSettings
from typing import List, Literal

class Settings(BaseSettings):
    PROJECT_NAME: str = "Stackwise"
    API_V1_STR: str = "/api/v1"
    # Release tag: keep in sync with `frontend/package.json` and
    # `frontend/src/config.ts` (the version badge).
    APP_VERSION: str = "1.8.0-alpha"

    # Deployment database. Present for docker-compose/Vercel parity; the async
    # engine below connects through `SQLALCHEMY_URL` (see app/db/session.py).
    DATABASE_URL: str = "postgresql://postgres:postgres@db:5432/stackwise"
    SQLALCHEMY_URL: str = "sqlite+aiosqlite:///./stackwise.db"
    # Log every SQL statement (development only).
    SQLALCHEMY_ECHO: bool = False
    # How the engine talks to a hosted connection pooler. `auto` decides from the
    # URL (a transaction pooler on :6543 — Supabase's `…pooler.supabase.com:6543`
    # — cannot keep server-side prepared statements, so both caches are disabled
    # and no connection is pooled); `direct` and `transaction` force the answer
    # for a pooler that listens elsewhere. Ignored for non-PostgreSQL URLs.
    SQLALCHEMY_POOL_MODE: Literal["auto", "direct", "transaction"] = "auto"

    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    CORS_ORIGINS: List[str] = ["*"]

    # --- accounts: sign-in hardening -----------------------------------------
    # Attempts accepted per minute and per client address. Registration bounds
    # account creation from one place; login bounds credential stuffing against
    # many accounts from one address and brute force against one account from
    # many. Process-local, like every other limit here: a multi-worker
    # deployment wants the same ceiling at the edge as well.
    AUTH_REGISTER_RATE_LIMIT_PER_MINUTE: int = 5
    AUTH_LOGIN_RATE_LIMIT_PER_MINUTE: int = 10

    # --- public origins ------------------------------------------------------
    # The API's own origin (builds OAuth redirect URIs) and the SPA's (the browser
    # is sent back there after a provider round-trip). Both must match what is
    # registered in the provider consoles.
    API_PUBLIC_URL: str = "http://localhost:8001"
    FRONTEND_URL: str = "http://localhost:3000"

    # --- OAuth providers -----------------------------------------------------
    # Optional by design: a provider without a client id/secret is reported as
    # disabled by `GET /auth/providers` and its button stays hidden in the SPA.
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""

    # Signed state handed to the provider and checked on the way back (CSRF).
    OAUTH_STATE_EXPIRE_MINUTES: int = 10

    # --- development-only mock provider -------------------------------------
    # Registers `/auth/oauth/mock`, a local stand-in for a provider: a consent
    # screen served by this API that signs in as a fixed `example.com` identity
    # without contacting anyone. Lets the whole flow be exercised without
    # registering OAuth apps. NEVER enable this on a reachable deployment.
    DEV_OAUTH_MOCK: bool = False

    # GitHub REST base. Override for GitHub Enterprise / a self-hosted API.
    GITHUB_API_BASE_URL: str = "https://api.github.com"

    # Self-hosted GitHub Enterprise usually lives on a private address. Enabling
    # this turns off the private/loopback/metadata-IP guard for that one host
    # (see app/services/github.py::validate_github_base_url).
    ANALYSIS_ALLOW_PRIVATE_GIT_HOSTS: bool = False

    # --- analyzers -----------------------------------------------------------
    # Analyzer binaries are installed platform-wide (requirements.txt pins their
    # versions) and recorded per run; a project cannot pick versions.
    ANALYSIS_ENABLED_ANALYZERS: List[str] = ["ruff", "bandit", "radon"]
    # Deliberate, versioned rule selection rather than ruff's full default set:
    # syntax errors, pyflakes (undefined/unused names) and bugbear (bug risk).
    # A project may narrow this to a subset of the allowlist in
    # app/analysis/config.py.
    ANALYSIS_RUFF_SELECT: str = "E4,E7,E9,F,B"
    ANALYSIS_RUFF_TIMEOUT_SECONDS: float = 60.0
    ANALYSIS_BANDIT_TIMEOUT_SECONDS: float = 60.0
    ANALYSIS_RADON_TIMEOUT_SECONDS: float = 60.0
    # Upper bound a project-level timeout is clamped to.
    ANALYSIS_MAX_ANALYZER_TIMEOUT_SECONDS: float = 120.0
    # Radon cyclomatic complexity above this value becomes a finding.
    ANALYSIS_COMPLEXITY_FINDING_THRESHOLD: int = 11
    ANALYSIS_COMPLEXITY_HIGH_THRESHOLD: int = 21
    # Maintainability index ranks (radon: A ≈ 20-100, B ≈ 10-19, C ≈ 0-9) that
    # are reported as maintainability findings.
    ANALYSIS_MAINTAINABILITY_MIN_RANK: str = "B"

    # --- resource limits -----------------------------------------------------
    ANALYSIS_MAX_ARCHIVE_SIZE_MB: int = 10
    ANALYSIS_MAX_EXTRACTED_SIZE_MB: int = 50
    ANALYSIS_MAX_FILE_COUNT: int = 500
    ANALYSIS_MAX_FILE_SIZE_KB: int = 1024
    ANALYSIS_MAX_WORKSPACE_DEPTH: int = 12
    # Uncompressed/compressed ratio above which an entry is treated as a bomb.
    ANALYSIS_MAX_COMPRESSION_RATIO: int = 200
    ANALYSIS_MAX_ANALYSIS_DURATION_SECONDS: int = 300
    ANALYSIS_MAX_FINDINGS_PER_RUN: int = 2000
    # Per-process stdout/stderr cap for one analyzer invocation.
    ANALYSIS_MAX_ANALYZER_OUTPUT_BYTES: int = 2_000_000
    ANALYSIS_ANALYZER_MEMORY_MB: int = 1024
    ANALYSIS_ANALYZER_CPU_SECONDS: int = 120
    ANALYSIS_MAX_CONCURRENT_RUNS: int = 2
    # How long a dispatched run may wait for a free execution slot before it is
    # failed with `rate_limited` (a bounded queue instead of an unbounded one).
    ANALYSIS_QUEUE_WAIT_SECONDS: int = 120
    # In-flight ceilings. A run is created together with its project, so a project
    # never queues more than one at a time: today only the per-user ceiling binds,
    # and the per-project value stays as the documented platform ceiling.
    ANALYSIS_MAX_ACTIVE_RUNS_PER_PROJECT: int = 3
    ANALYSIS_MAX_ACTIVE_RUNS_PER_USER: int = 5
    # Analysis-start requests accepted per user per minute (process-local).
    ANALYSIS_RATE_LIMIT_PER_MINUTE: int = 10
    # Rejected before the body is read (JSON bodies only).
    ANALYSIS_MAX_REQUEST_BODY_BYTES: int = 16_000_000
    # A run still `pending`/`running` after started_at + the analysis budget plus
    # this grace period is reaped to `failed` so it cannot hang forever.
    ANALYSIS_STALE_RUN_GRACE_SECONDS: int = 600

    # --- findings agent ------------------------------------------------------
    # The chat that explains analyzer findings (app/agent/). Two runtimes, both
    # optional and both honest about it:
    #   `qwen`       — a local checkpoint through transformers. Its libraries are
    #                  deliberately absent from requirements.txt, so it reports
    #                  itself unavailable until `pip install -r
    #                  requirements-agent.txt`.
    #   `cloudflare` — a hosted Workers AI model over HTTPS. Nothing to install;
    #                  it needs the two settings below instead.
    # Either way the API answers 503 with the reason rather than generating
    # something on its own.
    AGENT_BACKEND: str = "qwen"  # qwen | cloudflare | none
    AGENT_MODEL_ID: str = "Qwen/Qwen2.5-0.5B-Instruct"  # the local checkpoint
    AGENT_MODEL_PATH: str = ""  # local weights directory (offline hosts)
    AGENT_DEVICE: str = "cpu"  # cpu | cuda | mps
    AGENT_TEMPERATURE: float = 0.2  # 0 → greedy decoding
    AGENT_MAX_NEW_TOKENS: int = 512
    AGENT_TIMEOUT_SECONDS: float = 120.0
    # Context budget: what one generation may carry, and what keeps it bounded.
    AGENT_MAX_MESSAGES: int = 20
    AGENT_MAX_MESSAGE_CHARS: int = 4000
    AGENT_MAX_CONTEXT_FINDINGS: int = 60
    AGENT_MAX_CONTEXT_CHARS: int = 12000
    # Agent requests accepted per user per minute (per worker process).
    AGENT_RATE_LIMIT_PER_MINUTE: int = 8

    # --- Cloudflare Workers AI (AGENT_BACKEND=cloudflare) --------------------
    # Server-side secrets: the token travels in the `Authorization` header of a
    # request made by this process and is never sent to the browser, echoed in an
    # error or written to a log. Both must be set for the backend to be available.
    CLOUDFLARE_ACCOUNT_ID: str = ""
    CLOUDFLARE_API_TOKEN: str = ""
    # Catalogue id, not a Hugging Face one: `@cf/<vendor>/<model>`.
    CLOUDFLARE_MODEL_ID: str = "@cf/qwen/qwen2.5-coder-32b-instruct"

    class Config:
        env_file = ".env"

settings = Settings()
