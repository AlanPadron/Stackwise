# Stackwise

> Multi-language code analysis platform for software repositories.

Stackwise analyzes an uploaded source archive (ZIP) and reports code quality, security and
complexity findings through a web dashboard.

**Status: functional MVP.** What used to be the v0.1.0 skeleton is now an end-to-end slice:
sign up → create a project → upload a ZIP → background static analysis → dashboard metrics and
per-run findings. The API is published as `1.0.0` (see `app/main.py`); only Python code is
analyzed today.

---

## What works today

- Email/password accounts with bcrypt hashing and JWT (HS256) bearer auth.
- Projects CRUD, scoped to their owner (cross-account access returns `403`).
- ZIP upload per project → asynchronous analysis run with `pending → processing → completed | failed`.
- Static analysis with **ruff** (lint), **bandit** (security) and **radon** (cyclomatic complexity).
- Per-run summary (`total_findings`, `severity_counts`) and a user-level dashboard summary.
- SPA with login/register, project list, project detail, ZIP upload, analysis history, findings
  list, protected routes, dark mode and a once-per-session splash screen.

## Not implemented yet

- Repository integration — analysis is ZIP upload only.
- Languages other than Python — all three bundled analyzers are Python-only.
- Job queue — analyses run in-process via FastAPI `BackgroundTasks` (`app/workers/` is empty).
- Alembic revisions — `alembic/versions/` is empty; tables come from `init_db.py`.
- Postgres in practice — `app/db/session.py` hard-codes SQLite (see *Database*).
- Password reset, refresh tokens, rate limiting.

---

## Architecture

```
Stackwise/
├── app/                    FastAPI backend
│   ├── main.py             app instance, CORS, /health, /api/v1 router
│   ├── api/deps.py         OAuth2PasswordBearer dependency -> current user email
│   ├── api/v1/             auth.py, projects.py, analyses.py, dashboard.py
│   ├── core/               config.py (pydantic-settings), security.py (bcrypt + JWT)
│   ├── db/session.py       async SQLAlchemy engine + session factory
│   ├── models/             User, Project, AnalysisRun, Finding
│   ├── schemas/            Pydantic request/response models
│   ├── services/           analysis_service.py — pipeline orchestration
│   ├── analyzers/          engine.py (ruff/bandit/radon), utils.py (ZIP validation)
│   └── utils/, workers/    empty placeholders
├── frontend/               React 18 + TypeScript + Vite SPA
│   └── src/                api/client.ts, context/, pages/, components/
├── tests/                  pytest + httpx ASGI tests
├── alembic/                migration scaffold (no revisions yet)
├── init_db.py              create the tables (dev)
├── create_admin.py         seed admin@stackwise.com / 1234
└── Dockerfile, docker-compose.yml
```

Request flow:

1. `POST /api/v1/projects/{id}/analyses` (multipart ZIP) → ownership check → ZIP copied to a
   temp file → `AnalysisRun(status="pending")` → `202 Accepted`.
2. A FastAPI background task runs the pipeline: `status="processing"` → ZIP validated and
   extracted to a temp dir → analyzers executed → findings persisted → summary written →
   `status="completed"` (on error: `failed` plus `error_message`).
3. The SPA polls `GET /projects/{id}/analyses` and renders `GET /analyses/{id}/findings`.

---

## Analysis pipeline

| Tool | Invocation | Reported as |
|---|---|---|
| ruff | `ruff check . --output-format=json` | lint findings; ruff has no severity levels, so `E9xx`/`F82x` map to `high` and everything else to `low` |
| bandit | `bandit -r . -f json -q` | security findings with bandit's own severity (`HIGH`/`MEDIUM`/`LOW` → lowercased) |
| radon | `radon cc . -s --json` | cyclomatic complexity > 10 (`medium`, `high` at ≥ 20) |

Analyzer binaries are looked up on `PATH`, falling back to the bin directory of the running
interpreter, so ruff/bandit/radon installed in the project venv are found even when uvicorn is
started without activating it. Subprocesses run with `shell=False` and a 30 s timeout.

ZIP handling (`app/analyzers/utils.py`) rejects invalid archives, aborts on ZIP-Slip paths, and
enforces `MAX_FILES_COUNT` and `MAX_UNCOMPRESSED_SIZE_MB`. Temp files and directories are
removed after every run.

---

## Tech stack

| Layer | Stack |
|---|---|
| Backend | Python 3.12+ (developed on 3.14), FastAPI, SQLAlchemy 2.0 async, Pydantic v2, python-jose, bcrypt |
| Frontend | React 18, TypeScript, Vite, react-router-dom 6, axios, Tailwind CSS |
| Analysis | ruff, bandit, radon |
| Storage | SQLite (`aiosqlite`) in dev; PostgreSQL 15 in `docker-compose.yml` |

---

## Getting started

### Backend

```bash
python -m venv venv
./venv/bin/pip install -r requirements.txt
cp .env.example .env                    # set a real SECRET_KEY
./venv/bin/python init_db.py            # create the tables in ./stackwise.db
./venv/bin/python create_admin.py       # optional: admin@stackwise.com / 1234
./venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

API on <http://localhost:8001> — `GET /health`, interactive docs at `/docs`.

Run it on **port 8001**: the Vite dev server proxies `/api` there (see below).

### Frontend

```bash
cd frontend
npm install
npm run dev        # http://localhost:3000
```

`frontend/vite.config.ts` proxies `/api` → `http://localhost:8001`, and `src/api/client.ts`
defaults to the relative `/api/v1` base URL so requests go through that proxy. Override with
`VITE_API_URL` to point at a different backend.

---

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | — (required) | Declared as required by `Settings`; **currently unused at runtime** — `app/db/session.py` hard-codes `sqlite+aiosqlite:///./stackwise.db` |
| `SECRET_KEY` | — (required) | JWT signing key (HS256) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | Access-token lifetime |
| `CORS_ORIGINS` | `["*"]` | Origins allowed by the CORS middleware |
| `MAX_FILES_COUNT` | `500` | Maximum entries per uploaded ZIP |
| `MAX_UNCOMPRESSED_SIZE_MB` | `50` | Maximum total uncompressed size |
| `MAX_ZIP_SIZE_MB` | `10` | Defined but not enforced yet (only the uncompressed size is checked) |

---

## API (base path `/api/v1`)

| Method | Path | Auth | Notes |
|---|---|---|---|
| `POST` | `/auth/register` | – | `201`, `400` on duplicate email; password ≥ 8 chars |
| `POST` | `/auth/login` | – | form data `username` (email) + `password` → `200` `{access_token, token_type}` |
| `GET` | `/auth/me` | Bearer | Current user profile; `401` on invalid token |
| `POST` | `/projects` | Bearer | `201` |
| `GET` | `/projects` | Bearer | Current user's projects |
| `GET` | `/projects/{project_id}` | Bearer | `403` if not the owner |
| `PATCH` | `/projects/{project_id}` | Bearer | Update name/description |
| `DELETE` | `/projects/{project_id}` | Bearer | `204` |
| `POST` | `/projects/{project_id}/analyses` | Bearer | Multipart `file` (ZIP) → `202` with the pending run |
| `GET` | `/projects/{project_id}/analyses` | Bearer | Analysis history for a project |
| `GET` | `/analyses/{analysis_id}` | Bearer | Poll status/summary |
| `GET` | `/analyses/{analysis_id}/findings` | Bearer | Findings of a completed run |
| `GET` | `/dashboard/summary` | Bearer | `total_projects`, `total_analyses`, `completed_analyses`, `total_findings`, `findings_by_severity`, `last_analysis_status` |

`GET /health` lives outside the `/api/v1` prefix. All project and analysis routes resolve the
project owner and return `403` for foreign resources.

---

## Database

Models (`app/models/`): `users`, `projects`, `analysis_runs`, `findings`, with UUID primary keys
and cascading deletes from project → runs → findings.

Development uses SQLite at `./stackwise.db` (created by `init_db.py`, git-ignored). A Postgres
service is defined in `docker-compose.yml` and sets `DATABASE_URL`, but the async engine ignores
it today — switching to Postgres means changing `app/db/session.py` (and the model columns that
already use the Postgres `UUID` dialect are ready for it). Alembic is configured
(`alembic.ini`, `alembic/env.py`) but no revisions have been generated.

---

## Tests

```bash
./venv/bin/python -m pytest -q        # 3 passed
```

Use `python -m pytest`, not the bare `pytest` entry point: the latter does not put the repository
root on `sys.path` and fails with `ModuleNotFoundError: No module named 'app'`.

Covered: register → login → `/auth/me`, `401` on invalid credentials, `400` on duplicate
registration. The suite runs against the development SQLite database (no isolated test fixture
yet).

---

## Docker

```bash
docker compose up --build
```

The image (`python:3.12-slim`) installs the requirements plus ruff/bandit/radon and serves the API
on `:8000`; `db` is `postgres:15-alpine`. Caveats: the app still uses SQLite inside the container
(it ignores `DATABASE_URL`), and the frontend is not part of the compose stack.

---

## Next steps

- Enforce `MAX_ZIP_SIZE_MB` on upload (today only the uncompressed size is limited).
- Reject symlink/special-file ZIP entries — that check in `app/analyzers/utils.py` is currently a
  no-op (path containment is validated).
- Replace `BackgroundTasks` with a real worker (`app/workers/`), so in-flight runs survive restarts.
- Add Alembic revisions and make Postgres the default backend.
- Extend beyond Python and add repository integration.
