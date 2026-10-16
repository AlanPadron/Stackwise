# Analysis engine

The engine is the backend half of Stackwise: it takes an **untrusted** source
snapshot, runs static analyzers over it under explicit resource limits, normalises
every tool's output into one schema, computes metrics and heuristic indicators,
and persists the result. The frontend only renders what the API returns; it never
implements a rule, a severity, a metric or a score.

```
POST /projects/from-repo      ──▶ AnalysisRun(pending) ──▶ 201
        (dispatcher)
              │
        ┌─────▼──────────────────────────────────────────────────────────┐
        │ source provider → workspace → inventory → analyzers → normalise │
        │ → deduplicate → metrics → risk → persist → terminal status      │
        └────────────────────────────────────────────────────────────────┘
GET /analyses/{id}            ◀── status, summary, metrics, risk
GET /analyses/{id}/findings   ◀── canonical findings (paged, filtered)
GET /findings/{id}            ◀── one finding, ownership checked
```

## 1. Components

| Component | Module | Responsibility |
|---|---|---|
| Configuration | `app/analysis/config.py` | Platform ceiling + validated project/run overrides; `config_hash` |
| Source providers | `app/analysis/sources/` | Turn "where the bytes are" into a validated snapshot |
| Workspace | `app/analysis/workspace.py` | One private temp tree per run; always deleted |
| Repository inspector | `app/analysis/inventory.py` | Deterministic file discovery, language detection, exclusions, safe reads |
| Analyzer registry | `app/analysis/registry.py` | Which analyzers exist, which languages they cover, which are enabled |
| Analyzer runner | `app/analysis/runner.py` | Controlled subprocess execution (argv, env scrub, rlimits, timeouts, bounded output) |
| Analyzers | `app/analysis/analyzers/{ruff,bandit,radon}.py` | Invocation, parsing, severity mapping, raw metrics |
| Normaliser | `app/analysis/normalize.py` | Canonical finding shape, fingerprints, deduplication |
| Metrics | `app/analysis/metrics.py` | Objective counts and measurements |
| Risk | `app/analysis/risk.py` | Versioned heuristic indicators |
| Persistence | `app/analysis/persistence.py` | Runs, findings (batched, idempotent), metrics |
| Lifecycle | `app/analysis/status.py` | Allowed transitions, terminal states, stale-run recovery |
| Orchestrator | `app/analysis/orchestrator.py` | The pipeline itself, partial success, cleanup |
| Dispatch | `app/analysis/dispatch.py` | The seam between "accepted" and "executed" |

## 2. Source acquisition

One source provider remains, and it produces a `SourceSnapshot` (root directory,
origin, content hash) from the **GitHub zipball** (`POST /projects/from-repo`),
downloaded with the user's own OAuth token, never a service token.

The provider hands the zipball to `app/analysis/sources/archive.py`, which
validates the archive and then extracts it in a single pass over one `ZipFile`
handle:

| Guard | Behaviour |
|---|---|
| Archive size | `ANALYSIS_MAX_ARCHIVE_SIZE_MB`, enforced while the download streams |
| Entry count | `ANALYSIS_MAX_FILE_COUNT` |
| Per-file size | `ANALYSIS_MAX_FILE_SIZE_KB`, re-checked against the bytes actually written |
| Total extracted size | `ANALYSIS_MAX_EXTRACTED_SIZE_MB`, also re-checked while writing |
| Compression ratio | `ANALYSIS_MAX_COMPRESSION_RATIO` (archive bombs, including entries that lie about their size) |
| Nesting depth | `ANALYSIS_MAX_WORKSPACE_DEPTH` |
| Path safety | absolute paths, drive letters, `..`, NUL/control characters, over-long names → rejected |
| Entry kind | symlinks, FIFOs, sockets, devices → rejected; only regular files and directories |
| Empty archive / no files | rejected |

GitHub's zipball wraps everything in `repo-<ref>/`; when the extraction directory
holds exactly one directory, that directory becomes the repository root, so
findings are reported as `app.py`, not `repo-main/app.py`. A `source_hash`
(sha256 over relative paths, sizes and contents) identifies the analysed snapshot.

Adding a provider (a git clone, a stored snapshot) means implementing
`SourceProvider` and choosing it in the orchestrator; nothing else changes.

## 3. Inventory, languages and exclusions

`RepositoryInspector` walks the tree once, in sorted order, so the same archive
always produces the same inventory, fingerprints and metrics.

* **Language detection** (`LanguageDetector`) uses the *basename* extension
  (`.py`, `.pyi`, `.pyw`, `.py3`) and, for extensionless files, a
  `python*` interpreter shebang. An extension appearing in a *directory* name
  (`pkg.py/module.txt`) never makes a file Python, and content is not sniffed for
  language guessing — false positives there are undebuggable for a user.
  Python is the only supported language today; the registry and the inventory
  already key on language, so adding one is a registry change plus an analyzer.
* **Exclusions** are centralised in `ExclusionPolicy`:
  * *mandatory* (never configurable): VCS metadata (`.git`, `.hg`, `.svn`),
    non-regular files, symlinks, control characters in a name, over-long paths,
    files above the size limit;
  * *default*: dependency and build directories (`node_modules`, `venv`,
    `__pycache__`, `build`, `dist`, `target`, caches…), binary extensions,
    minified files, lock files, generated files (a `DO NOT EDIT`/`@generated`
    marker in the first 2KB), packaging metadata;
  * *project*: `analysis_config.excluded_paths` globs, matched against the whole
    relative path **and** each directory segment, so `"tests"` behaves as
    expected. A pattern that would exclude everything (`**`, `*`, `/`) is
    rejected at configuration time.
* Every skipped file is recorded with a reason and counted
  (`metrics.files.skipped_by_reason`), so a run can explain itself.
* Reads go through `SourceReader`, which refuses absolute paths, `..`, symlinks,
  files outside the root and files over the limit, then counts lines in a
  streaming pass and flags binary content.
* Source contents are **never** stored in the database.

## 4. Analyzers

All three are invoked with an absolute executable path and an argument vector
(`shell=False`), from the run's neutral working directory, with absolute file
paths. The registry decides applicability:

| Analyzer | Invocation | Category | Reports |
|---|---|---|---|
| ruff | `ruff check --isolated --no-cache --output-format=json --select <rules> <files…>` | lint | lint/defect findings |
| bandit | `bandit --format json --quiet <files…>` | security | security findings |
| radon | `radon cc -s -j <files…>`, `radon mi -j`, `radon raw -j` | metrics | complexity + maintainability findings, raw metrics |

* `--isolated` makes ruff ignore **every** configuration file in the repository:
  a project cannot change what the platform checks. bandit and radon run with a
  neutral cwd for the same reason (their config discovery walks up from the cwd).
* Exit code `0` = clean, `1` = findings (a normal result, **not** a failure),
  anything else = a failure classified from stderr (`invalid_config` vs
  `execution_error`).
* Analyzer output is read from temp files and truncated at
  `ANALYSIS_MAX_ANALYZER_OUTPUT_BYTES`; a truncated report is an
  `output_limit` failure rather than a silently partial parse.
* Analyzer versions are pinned in `requirements.txt` and recorded per run in
  `analysis_runs.tool_versions`. Per-project version selection is not supported:
  the binaries are shared by the whole process.

### Severity mapping (documented, not pretended equivalent)

`critical` exists in the canonical scale but no current analyzer emits it; it is
reserved for future tools and for callers that map their own severity.

**ruff** (no severities of its own — this table is the policy):

| Severity | Rules |
|---|---|
| high | `invalid-syntax`, `E902`, `F811`, `F821`, `F822`, `F823` |
| medium | `E711`, `E712`, `E713`, `E714`, `E721`, `E722`, `E731`, `B*` (bugbear), `S<digits>` (flake8-bandit), `TRY`, `RET`, `PIE`, `ARG`, `TID` |
| low | everything else (hygiene: `F401`, `F841`, `F5xx`, `E4xx`, `SIM`, `UP`, `I`, `RUF`, …) |

Categories: `dead_code` (`F401`, `F841`), `bug` (high/medium codes, `E9`, `F7/F8`,
bugbear), `security` (`S<digits>`), `style` (`E4/E5/E7`, `SIM`, `UP`, `I`, `RUF`,
`F5xx`), `other`.

**bandit**: `HIGH → high`, `MEDIUM → medium`, `LOW → low`, `UNDEFINED → info`.
Confidence is kept as its **own** field (`HIGH/MEDIUM/LOW → high/medium/low`), so
a heuristic signal is never presented as certainty. The rule id, CWE reference and
`more_info` URL are preserved; the raw `code` snippet is deliberately dropped
(findings are returned to clients and can contain credentials).

**radon**: a block at or above `ANALYSIS_COMPLEXITY_FINDING_THRESHOLD` (default
11, i.e. rank C) is a `complexity` finding — `medium`, and `high` at or above
`ANALYSIS_COMPLEXITY_HIGH_THRESHOLD` (default 21). A file whose maintainability
rank is at or below `ANALYSIS_MAINTAINABILITY_MIN_RANK` (default B) is a
`maintainability` finding — `low` for rank B, `medium` for rank C.

## 5. Canonical finding schema

`findings` (see `app/models/analysis.py`):

| Field | Notes |
|---|---|
| `tool`, `rule_id` | original analyzer and rule identity, preserved |
| `category` | `security`, `bug`, `complexity`, `maintainability`, `style`, `dead_code`, `performance`, `other` |
| `severity` | `critical`, `high`, `medium`, `low`, `info` |
| `confidence` | `high`, `medium`, `low` or null — never folded into severity |
| `title` / `message` | short label / full description (the tools' `message`, `issue_text`, …) |
| `file_path` | **repository-relative posix**, always |
| `line_start/end`, `column_start/end` | integers, nullable when the tool does not say |
| `fingerprint` | 32 hex chars, stable, contains no source text (see below) |
| `references` | http(s) links plus short identifiers (e.g. `CWE-78`) |
| `metadata` | JSON-safe, redacted, bounded (4KB) |
| `project_id` | denormalised from the run for the "findings by project and severity" query |

Normalisation (`FindingNormalizer`) drops a finding whose path cannot be mapped
into the workspace, degrades unknown vocabularies (`severity → info`,
`category → other`) while recording the original value in `metadata`, redacts
secret-shaped strings, bounds every text field, and tracks every drop with a
reason (`metrics.findings.dropped_by_reason`). Malformed analyzer output never
crashes the run.

**Fingerprint** = `sha256(tool, rule_id, category, file_path, line_start, identity)`
truncated to 32 hex characters, where `identity` is a rule-specific stable
identifier (e.g. `Svc.run` for a complexity finding). It never includes code, a
snippet, or a message, so it is stable across wording changes and cannot leak
source. Identical fingerprints inside one run are collapsed (duplicates
counted); findings from **different** analyzers at the same line are never
merged — two tools at one location are two different problems.

## 6. Metrics

`analysis_runs.metrics` (see `app/analysis/metrics.py`):

```
engine_version, config_version, config_hash, source_hash, duration_seconds, languages,
files   { discovered, analyzed, skipped, unsupported_language, failed, directories,
          directories_skipped, symlinks_skipped, total_bytes, file_count_limit_reached,
          skipped_by_reason{}, failures[] }
lines   { physical, source, logical, comments, physical_by_language{}, method }
findings{ total, by_severity{}, by_category{}, by_analyzer{}, by_confidence{},
          files_with_findings, findings_per_analyzed_file, duplicates_removed,
          dropped_invalid, dropped_by_reason{}, truncated }
complexity      { … } | null      ← radon cc
maintainability { … } | null      ← radon mi
raw_source      { … } | null      ← radon raw
analyzers { applicable, succeeded, failed, skipped, complete, items{ name: {status,
          version, duration_seconds, exit_code, findings, error_category, message} } }
limits   { … the effective configuration … }
exclusions[]
```

Rules that make these numbers trustworthy:

* **unavailable ≠ zero.** A metric that could not be measured is `null`; a failed
  radon never becomes "0 complexity".
* **documented counting method.** `lines.method` states it: `physical` is the
  newline count per analysed file (always available); `source`/`logical` come from
  radon's `sloc`/`lloc`. Radon's `sloc` counts source lines (statements +
  comments, blank lines excluded) and `lloc` counts logical lines, so a
  comment-heavy file scores *worse* on the maintainability index than its physical
  size suggests — a property of the metric, not of the code.
* **objective counts stay separate from derived judgement.** Findings are never
  re-encoded as metrics, and metrics are never scored.
* per-file detail is capped (`_MAX_FILES_IN_METRICS`) so one run cannot write an
  unbounded JSON blob.

## 7. Risk indicators

`analysis_runs.risk`, algorithm version `risk-1` (`app/analysis/risk.py`). This is
a **heuristic**, and the document says so (`heuristic: true`, plus notes). It is
not a probability of exploitation, not an audit result, and not comparable across
projects with different configurations.

```
severity weights       critical 10, high 5, medium 2, low 0.5, info 0
quality multipliers    bug 0.75, complexity 1.0, maintainability 0.5,
                       performance 0.5, dead_code 0.25, style 0.1, other 0.25

security.points = Σ severity_weight over findings with category == "security"
quality.points  = Σ severity_weight × quality_multiplier over the remaining findings

band     points == 0 → "none"; ≤ 5 → "low"; ≤ 20 → "moderate"; > 20 → "high"
index    100 × (1 − min(1, points / saturation)), saturation 50 (security),
         60 (quality); 100 = no weighted points found, 0 = saturation or worse
overall  index = 0.75 × security.index + 0.25 × quality.index
```

* **The security signal is load-bearing.** If no security analyzer produced
  results (missing, timed out, crashed, or none applies to the analysed
  languages), `security.available` is false and `overall.index` is **null**, with
  a reason. The engine refuses to report a safe-looking number when the security
  evidence is missing.
* If quality is unavailable but security is present, the overall index falls back
  to security alone and the weights in the document say so
  (`{"security": 1.0, "quality": 0.0}`).
* Duplicates are already collapsed before scoring, so a tool that reports the same
  issue twice cannot double-count. Scoring is a pure function of the deduplicated
  findings and the analyzer outcomes: the same inputs and configuration always
  produce the same numbers (no clock, no ordering, no randomness).
* `inputs` echoes the raw points and the weight tables, so a client can recompute
  every number from the findings it can already fetch.

## 8. Lifecycle

```
pending ──▶ running ──┬─▶ completed                 every applicable analyzer succeeded
   │                  ├─▶ completed_with_errors      ≥1 analyzer failed, others produced results
   │                  └─▶ failed                     no analyzer produced results, or a fatal error
   └────────▶ failed / cancelled                     never started (or refused)
   terminal: completed, completed_with_errors, failed, cancelled
```

* Transitions are validated (`AnalysisStatusService.ensure_transition`); a
  terminal state cannot be left, and a second dispatch of a finished run is a
  no-op.
* `completed` / `completed_with_errors` are written **together with** the
  findings, summary, metrics and risk in one transaction
  (`AnalysisPersistenceService.persist_results`), so a run never claims to be
  complete before its results are durable.
* A fatal error (invalid archive, resource limit, configuration refused,
  orchestration failure, persistence failure) records the matching
  `error_category` and a sanitised `error_message`.
* **Recovery:** `reap_stale_runs()` fails any run still `pending`/`running` past
  `ANALYSIS_MAX_ANALYSIS_DURATION_SECONDS + ANALYSIS_STALE_RUN_GRACE_SECONDS`
  with `error_category = stale_run`. It runs at application startup and on the
  run-listing/polling endpoints, so a worker that died cannot leave a run looking
  busy forever.

## 9. Execution, isolation and limits

### What the runner guarantees

* No shell, ever: argument vectors with absolute executables (`shell=False`).
* A **scrubbed environment** built from scratch: `PATH`, locale, `HOME`/`TMPDIR`
  inside the run's private temp tree and a few deterministic flags. `SECRET_KEY`,
  `DATABASE_URL`, `SUPABASE_*`, `GITHUB_*`/`GOOGLE_*` and everything else are
  inherited by nobody.
* A **neutral working directory**, so a repository cannot feed its own
  `pyproject.toml`, `.bandit` or `.radon.cfg` to a tool.
* **rlimits on POSIX**: CPU seconds, address space (`RLIMIT_AS`), written file
  size and core dumps. `RLIMIT_NPROC` is deliberately *not* set: it is accounted
  per real UID, so it would cap every process of the service account and make
  analyzers die trying to spawn threads.
* **Wall-clock timeout** with a process-*group* kill, so children do not survive.
* Bounded stdout/stderr (temp files, read back truncated) and bounded finding
  counts, so output cannot exhaust memory or the database.
* Repository code is never executed: no `eval`/`exec`, no imports of project
  modules, no `setup.py`, no package installs, no repository CI workflows.
* Temporary workspaces are `<mkdtemp>` (mode `0700`) and are removed in a
  `finally` block on success, failure and interruption; the queued archive is
  deleted too.

### What it is not

**This is not a sandbox.** There is no syscall filtering, no user or mount
namespace, no cgroup, no network namespace and no dedicated VM: analyzers run as
the same OS user as the API, in the same network namespace, with the same
filesystem visibility (minus the environment and the rlimits above). A
determined attacker who finds a code-execution bug *in an analyzer* is not
contained by this design. Mitigations that do apply: the engine never executes
repository code, analyzers are the only binaries spawned, and they receive no
credentials.

`AnalyzerRunner` is the interface behind which a stronger isolation boundary can
be added (a container/job per run, a dedicated worker host) without changing the
orchestrator.

### Deployment model (honest status)

Analyses run **in the API worker** via a FastAPI background task
(`BackgroundTaskDispatcher`): the request returns `202` immediately and the SPA
polls `GET /analyses/{id}`. Consequences, stated plainly:

* a run does not survive a process restart or a serverless invocation that
  outlives the response — the stale-run reaper marks it `failed/stale_run` and the
  user can re-run it;
* the concurrency limit (`ANALYSIS_MAX_CONCURRENT_RUNS`) and the rate limiter are
  **per process**, so they bound one worker, not a fleet;
* on Vercel, function time limits and a read-only/ephemeral filesystem make this
  path suitable only for small repositories; the smallest viable production
  setup is one always-on container running the same app image (or a dedicated
  worker process calling `AnalysisOrchestrator.execute`) with a real queue in
  front of `AnalysisDispatcher`.

`analysis_runs.error_category` and `metrics.analyzers.items[*].status` make the
degraded paths observable rather than silent.

## 10. Configuration

Platform settings (environment, `.env`) are the **ceiling**; a project or a single
run can only narrow them. Overrides are validated and clamped *before* a run is
created: an out-of-range timeout or finding cap is refused with `422` (never
silently reduced), and a value that would escape a limit cannot be stored.

| Where | What |
|---|---|
| `ANALYSIS_*` env settings | analyzer enablement, ruff rule selection, timeouts, thresholds, all size/count/duration limits, concurrency, rate limit, request body size |
| `projects.analysis_config` (`PATCH /projects/{id}`) | `excluded_paths`, `enabled_analyzers`, `ruff_select`, `complexity_threshold`, `maintainability_rank`, `max_findings_per_run`, `analyzer_timeout_seconds` |
| `POST /projects/from-repo` body field `analysis_config` | the same block, for the run the import starts (stored on the run; wins over the project) |

The resolved configuration is hashed into `analysis_runs.config_hash` and echoed
in `metrics.config_hash`, `metrics.limits` and `metrics.exclusions`, so a stored
run explains exactly what executed. See `.env.example` for every variable.

Example:

```bash
curl -X POST "$API/projects/from-repo" -H "$AUTH" -H "Content-Type: application/json" \
  -d '{"repository":"owner/name","ref":"main",
       "analysis_config":{"enabled_analyzers":["ruff","bandit"],"excluded_paths":["tests/**","migrations"],
                          "complexity_threshold":8,"max_findings_per_run":500}}'
```

## 11. Database

Five tables (`users`, `oauth_accounts`, `projects`, `analysis_runs`, `findings`)
with UUID primary keys and cascading deletes (user → oauth accounts, project →
runs → findings). Indexes are chosen against the actual query patterns:

| Index | Serves |
|---|---|
| `ix_users_email` (unique) | login / token subject lookup |
| `ix_oauth_accounts_user_id` | "which providers has this user linked" |
| `ix_analysis_runs_project_created` | project run history (newest first) |
| `ix_analysis_runs_status` | active-run caps, stale-run recovery |
| `uq_findings_run_fingerprint` (unique) | retry safety: a replayed run cannot duplicate a finding |
| `ix_findings_run_severity` | run findings filtered/paged by severity |
| `ix_findings_project_severity` | dashboard + project-level severity aggregates |

Migrations: `alembic/versions/d0be4f4dea77_baseline_schema_*.py` is the baseline
(every table, in the state this engine requires). It was generated from the models
and verified by applying it to a fresh database and comparing the DDL with
`Base.metadata.create_all`. Development runs on SQLite through a create-all path;
migrations are the path for a Postgres deployment. `alembic/env.py` translates an
async driver URL to its synchronous equivalent, so a migration always targets the
same database the application talks to (`ALEMBIC_DATABASE_URL` overrides it).

Note: `alembic check` may report a *spurious* type change for the UUID columns on
SQLite, because SQLite has no UUID affinity for the reflection to read back. The
migration uses the generic `sa.UUID()`, which renders as `UUID` on PostgreSQL and
as `UUID`-affinitised text on SQLite, matching `create_all` exactly.

Nothing about a run holds a database connection while analyzers execute: the only
statements are `pending → running` at the start and one transaction at the end.

Deletes cascade twice over: in the DDL (`ondelete="CASCADE"`) and in the ORM
(`cascade="all, delete-orphan"`). The second one is not enough on its own —
`POST /projects/from-repo` deletes a half-created project with a core `DELETE`,
which cannot cascade through the session — and SQLite does not enforce foreign
keys unless a connection asks it to. Every SQLite connection therefore issues
`PRAGMA foreign_keys=ON` (`app/db/session.py`); without it that rollback left
orphaned `analysis_runs` and `findings` rows behind, and SQLite disagreed with
PostgreSQL about what deleting a project means.

Running on PostgreSQL, Supabase included: install the async driver (`asyncpg`,
already in `requirements.txt`) and set
`SQLALCHEMY_URL=postgresql+asyncpg://<user>:<password>@<host>:5432/<db>?ssl=require`.
`DATABASE_URL` keeps the synchronous spelling for Alembic and docker-compose, and
`alembic/env.py` translates between the two. Two portability notes, both by
design rather than oversight: the JSON columns are generic `JSON`, not `JSONB`
(so no JSON operators or GIN indexes), and the timestamps are naive `DateTime`
values defaulted in Python, which PostgreSQL stores as `TIMESTAMP WITHOUT TIME
ZONE`.

## 12. API

| Method | Path | Notes |
|---|---|---|
| `POST` | `/api/v1/projects/from-repo` | JSON body (`repository`, optional `ref`/`name`/`description`/`analysis_config`) → `201` `{project, run}` with a pending run; `409` no GitHub account linked, `404` repository not accessible, `422` bad repository/ref/config, `502` GitHub failure or archive over the size limit |
| `GET` | `/api/v1/projects/{id}/analyses` | `limit`(≤200), `offset`, `status`, `source_type`; `X-Total-Count` |
| `GET` | `/api/v1/analyses/{id}` | status, summary, metrics, risk, tool versions |
| `GET` | `/api/v1/analyses/{id}/findings` | `limit`(≤200), `offset`, `severity`, `category`, `tool`, `rule_id`, `file_path`, `sort`; `X-Total-Count` |
| `GET` | `/api/v1/findings/{id}` | one finding, ownership checked |
| `GET` | `/api/v1/health` | `{status, version, engine_version, database}` — no secrets, no driver errors |
| `GET` | `/health` | unauthenticated liveness, answers even when the database is down |

Ownership is resolved in `app/api/deps.py` for every route (foreign resource →
`403`, unknown → `404`). A `SQLAlchemyError` becomes a `503` with a fixed detail
string; the driver's message (which can contain the connection string) only ever
goes to the log.

## 13. Observability

Structured log lines (`stackwise.analysis`) with the analysis run id as the
correlation key: `analysis_started`, `analysis_inventory`, `analyzer_finished`,
`analyzer_skipped_budget`, `analysis_failed`, `analysis_finished`,
`analysis_runs_reaped`, `analysis_persistence_failure`, `analyzer_crashed`. Field
values are redacted and bounded, so a log line cannot carry a token; source
contents and full file paths of user code are never logged.

Failure categories (`error_category`): `source_acquisition`, `invalid_source`,
`resource_limit`, `configuration`, `analyzer_unavailable`, `analyzer_timeout`,
`analyzer_execution`, `output_parsing`, `persistence`, `authorization`,
`rate_limited`, `stale_run`, `orchestration`. Per-analyzer detail lives in
`metrics.analyzers.items`.

## 14. Tests

The engine suite is the contract this document describes; every claim above is
pinned by a test, and the analyzers it drives are the real binaries rather than
doubles — a missing tool fails the suite instead of being papered over.

| File | Covers |
|---|---|
| `test_analysis_inventory.py` | language detection, exclusion policy, limits, symlinks, safe reads, determinism |
| `test_analysis_archive.py` | traversal/absolute/control names, symlink/FIFO entries, count/size/depth/ratio limits, provider snapshot + hashing |
| `test_analysis_analyzers.py` | parsing for all three tools, severity/category mapping, malformed output, missing executables, exit-code semantics, env scrubbing, timeouts, output truncation, rlimits, registry |
| `test_analysis_normalize.py` | path mapping, vocabulary degradation, redaction, metadata sanitisation, fingerprints, dedup, caps |
| `test_analysis_metrics.py` | counts, `null` vs `0`, LOC method, analyzer statuses, effective limits |
| `test_analysis_risk.py` | formula, band boundaries, determinism, degraded-signal behaviour, completeness |
| `test_analysis_lifecycle.py` | transition matrix, terminal states, sanitised errors, stale-run recovery, active-run counts |
| `test_analysis_pipeline.py` | real ruff/bandit/radon runs, persistence, partial failure, crash containment, invalid archive, retry idempotency, persistence failure, DB outage, project/run config |
| `test_analysis_api.py` | auth, ownership, 202/polling, pagination, filters, status codes, rate/in-flight caps, body size, health, DB-error handling, dashboard |
| `test_analysis_security.py` | malicious archives, no code execution, no repo config influence, analyzer cwd/env isolation, secret non-exposure, findings cap, timeout, SSRF guards, input validation |

Tests run against a throwaway SQLite database in a temp directory (see
`tests/conftest.py`); they never touch a developer's database, and they execute
the real analyzers, so a missing tool fails the suite instead of being papered
over.

Two groups sit outside the engine and are listed here for completeness:

| File | Covers |
|---|---|
| `test_agent_api.py`, `test_agent_prompt.py` | the findings agent's contract: authentication, ownership, request shape, the bounded context built from findings, and a `503` (rather than an invented answer) whenever the configured backend cannot run |
| `test_agent_cloudflare.py` | the hosted backend over a loopback HTTP server: request path, `Authorization` header, JSON body, Cloudflare's envelope and error shapes, timeouts, and that the API token never appears in a reason |
| `test_db_cascade.py` | deleting a project takes its runs and findings with it — including the core `DELETE` path, which depends on SQLite enforcing foreign keys |

## 15. Known limitations

* **No sandbox** (section 9) — the single most important limitation.
* **In-process execution**: no queue, no retries, no run cancellation
  (`cancelled` exists in the lifecycle but nothing produces it yet), no survival
  across restarts (the reaper cleans up instead).
* **Rate limiting and concurrency limits are per process.**
* **Python only.** The registry, inventory and normaliser are language-keyed, so
  a new language is a registry entry plus an analyzer, but nothing else ships
  today.
* **Per-project analyzer version selection is not supported** (binaries are
  process-wide); versions are pinned platform-wide and recorded per run.
* **`ruff_select` overrides are restricted** to a curated allowlist of stable rule
  families; arbitrary rule selection (and ruff plugins) is refused by design.
* **bandit's `nosec` comments are honoured**, so a repository can suppress its own
  bandit findings — visible only as a lower finding count.
* **No cross-run trend analysis** (per-run fingerprints exist; there is no
  project-level diff endpoint yet).
* **Alembic baseline is a single revision**: existing pre-engine databases are
  recreated from the models rather than migrated in place.
