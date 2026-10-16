"""Response schemas for analysis runs and findings.

`status`/`severity`/`category` stay plain strings here: the enums live in the
engine (`app/analysis/…`) and the DB, and a schema that rejects an unknown value
would turn an old row into a 500 instead of a readable response.
"""

from pydantic import BaseModel
from typing import Any, Optional
from uuid import UUID
from datetime import datetime


class AnalysisRunResponse(BaseModel):
    id: UUID
    project_id: UUID
    status: str
    source_type: str
    source_ref: Optional[str] = None
    source_hash: Optional[str] = None
    engine_version: Optional[str] = None
    config_version: Optional[str] = None
    config_hash: Optional[str] = None
    analysis_config: Optional[dict[str, Any]] = None
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    duration_seconds: Optional[float] = None
    error_category: Optional[str] = None
    error_message: Optional[str]
    summary: Optional[dict[str, Any]]
    metrics: Optional[dict[str, Any]] = None
    risk: Optional[dict[str, Any]] = None
    tool_versions: Optional[dict[str, Any]] = None
    created_at: datetime

    class Config:
        from_attributes = True


class FindingResponse(BaseModel):
    id: UUID
    analysis_run_id: UUID
    project_id: UUID
    tool: str
    rule_id: Optional[str]
    category: str
    severity: str
    confidence: Optional[str]
    title: str
    message: str
    file_path: str
    line_start: Optional[int]
    line_end: Optional[int]
    column_start: Optional[int] = None
    column_end: Optional[int] = None
    fingerprint: str
    references: Optional[dict[str, Any]] = None
    finding_metadata: Optional[dict[str, Any]] = None
    created_at: datetime

    class Config:
        from_attributes = True
