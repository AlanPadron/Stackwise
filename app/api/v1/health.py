"""Health probe.

Reports liveness and whether the database answers. It deliberately says nothing
else: no connection string, no driver error, no stack trace, no analyzer
inventory, no build metadata that could help map the infrastructure.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.config import ENGINE_VERSION
from app.core.config import settings
from app.db.session import get_db

router = APIRouter()


@router.get("/health")
async def api_health(db: AsyncSession = Depends(get_db)):
    """Readiness for the API, including a single `SELECT 1` against the database."""
    database = "ok"
    try:
        await db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - the probe reports, it never raises
        database = "unavailable"
    return {
        "status": "ok" if database == "ok" else "degraded",
        "version": settings.APP_VERSION,
        "engine_version": ENGINE_VERSION,
        "database": database,
    }
