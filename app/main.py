"""FastAPI application: middleware, router wiring and the health probes.

The version below is one of the three places the release tag lives (the others
are `frontend/package.json` and `frontend/src/config.ts`, which the version badge
in the SPA renders) — bump them together.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, APIRouter, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.analysis.config import ENGINE_VERSION
from app.analysis.status import AnalysisStatusService
from app.api.v1 import auth, oauth, github, projects, analyses, dashboard, agent, health
from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.services.oauth import MOCK_IDENTITY

logger = logging.getLogger("stackwise")

# A fake sign-in path is worth shouting about: it is opt-in and must never reach
# a reachable deployment.
if settings.DEV_OAUTH_MOCK:
    logging.getLogger("uvicorn.error").warning(
        "DEV_OAUTH_MOCK is enabled: /api/v1/auth/oauth/mock signs anyone in as %s "
        "without contacting a provider. Do not enable this outside local development.",
        MOCK_IDENTITY.email,
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Recover runs abandoned by a previous worker process, then serve.

    A run left `pending`/`running` by a crash would otherwise look busy forever;
    `reap_stale_runs` moves it to `failed` with `error_category=stale_run`.
    """
    async with AsyncSessionLocal() as session:
        try:
            reaped = await AnalysisStatusService(session).reap_stale_runs(grace_seconds=0)
            if reaped:
                logger.warning("Recovered %s analysis run(s) abandoned by a previous worker", reaped)
        except Exception:  # noqa: BLE001 - recovery must never block startup
            logger.exception("Stale analysis run recovery failed at startup")
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Backend for Stackwise - Code analysis platform",
    version=settings.APP_VERSION,
    lifespan=lifespan,
)


@app.middleware("http")
async def limit_request_body(request: Request, call_next):
    """Refuse oversized bodies before they are read.

    A client that omits `Content-Length` (chunked encoding) cannot slip past
    this check, but nothing here reads a body — the routes that accept one
    (`POST /projects/from-repo`) validate their own fields.
    """
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > settings.ANALYSIS_MAX_REQUEST_BODY_BYTES:
        return JSONResponse(status_code=413, content={"detail": "Request body is too large"})
    return await call_next(request)


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    """Report a database outage without leaking the driver's error text.

    SQLAlchemy exceptions carry connection strings, SQL statements and table
    names; none of that belongs in an HTTP response. The detail goes to the log.
    """
    logger.exception("Database error while handling %s %s", request.method, request.url.path)
    return JSONResponse(status_code=503, content={"detail": "The database is unavailable"})


# CORS: the SPA is served from another origin in dev (Vite on :3000).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Every route lives under /api/v1; analyses.py adds no prefix of its own because
# it serves both /projects/{id}/analyses and /analyses/{id}.
api_v1_router = APIRouter(prefix=settings.API_V1_STR)
api_v1_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_v1_router.include_router(oauth.router, prefix="/auth", tags=["Authentication"])
api_v1_router.include_router(github.router, prefix="/github", tags=["Repositories"])
api_v1_router.include_router(projects.router, prefix="/projects", tags=["Projects"])
api_v1_router.include_router(analyses.router, tags=["Analyses"])
api_v1_router.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])
api_v1_router.include_router(agent.router, prefix="/agent", tags=["Agent"])
api_v1_router.include_router(health.router, tags=["Health"])

app.include_router(api_v1_router)


@app.get("/health")
async def health_check():
    """Unauthenticated liveness probe, outside the /api/v1 prefix.

    Deep checks (database, analyzer inventory) live in `/api/v1/health`; this one
    answers even when the database is down.
    """
    return {"status": "healthy", "version": settings.APP_VERSION, "engine_version": ENGINE_VERSION}
