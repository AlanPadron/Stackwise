"""Analysis run + finding tables.

Cascades: deleting a project removes its runs and its findings; deleting a run
removes its findings (FK level and `delete-orphan`).

`findings.project_id` is a deliberate denormalisation: it is copied from the run
at persistence time and never updated, so it cannot drift, and it lets the
"findings by project and severity" query (dashboard, project filters) run
without a join. Both findings indexes below exist because those two queries are
the only hot read paths.
"""

import uuid
from datetime import datetime
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base

# Canonical lifecycle. `processing` is the pre-engine spelling and is still
# accepted when reading old rows (see app/analysis/status.py).
RUN_STATUSES = (
    "pending",
    "running",
    "completed",
    "completed_with_errors",
    "failed",
    "cancelled",
)

SEVERITIES = ("critical", "high", "medium", "low", "info")
CONFIDENCES = ("high", "medium", "low")
CATEGORIES = (
    "security",
    "bug",
    "complexity",
    "maintainability",
    "style",
    "dead_code",
    "performance",
    "other",
)


class AnalysisRun(Base):
    """One execution of the analyzer pipeline over one source snapshot."""

    __tablename__ = "analysis_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    source_type = Column(String(16), nullable=False, default="zip")  # zip (uploaded) | github (imported)
    # Human-readable origin of the snapshot (e.g. "octocat/hello-world@main").
    source_ref = Column(String(200), nullable=True)
    # sha256 over the extracted tree's files; identifies the analysed snapshot.
    source_hash = Column(String(64), nullable=True)
    engine_version = Column(String(32), nullable=True)
    config_version = Column(String(16), nullable=True)
    config_hash = Column(String(64), nullable=True)
    # Validated override block used for *this* run (None = the project's stored
    # block, or the platform defaults when the project has none). Storing it on
    # the run is what makes `config_hash` describe what actually executed.
    analysis_config = Column(JSON, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    # {total_findings, severity_counts{...}, category_counts{...}, files{...}, complete}
    summary = Column(JSON, nullable=True)
    # Objective counts/measurements (see app/analysis/metrics.py).
    metrics = Column(JSON, nullable=True)
    # Transparent heuristic indicators (see app/analysis/risk.py).
    risk = Column(JSON, nullable=True)
    # {analyzer: version} recorded per run.
    tool_versions = Column(JSON, nullable=True)
    # Sanitised error category + message; never a traceback or a secret.
    error_category = Column(String(32), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="analyses")
    findings = relationship("Finding", back_populates="analysis_run", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_analysis_runs_project_created", "project_id", "created_at"),
        Index("ix_analysis_runs_status", "status"),
    )


class Finding(Base):
    """A single issue reported by one analyzer, normalised to the canonical scale.

    Numbers are integers, not strings: line/column values come from the tools as
    integers and every consumer (API, SPA) compares them numerically.
    """

    __tablename__ = "findings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_run_id = Column(
        UUID(as_uuid=True), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False
    )
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    tool = Column(String(64), nullable=False)  # ruff | bandit | radon
    rule_id = Column(String(64), nullable=True)
    category = Column(String(32), nullable=False, default="other")
    severity = Column(String(16), nullable=False)
    confidence = Column(String(16), nullable=True)
    title = Column(String(200), nullable=False)
    # The canonical long description of the finding (tools' `message`/`issue_text`).
    message = Column(Text, nullable=False)
    file_path = Column(String(500), nullable=False)
    line_start = Column(Integer, nullable=True)
    line_end = Column(Integer, nullable=True)
    column_start = Column(Integer, nullable=True)
    column_end = Column(Integer, nullable=True)
    # Stable identity of the finding within its run (see app/analysis/normalize.py).
    fingerprint = Column(String(64), nullable=False)
    references = Column(JSON, nullable=True)
    # `metadata` is reserved on the declarative class, so the attribute differs
    # from the column name.
    finding_metadata = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    analysis_run = relationship("AnalysisRun", back_populates="findings")

    __table_args__ = (
        UniqueConstraint("analysis_run_id", "fingerprint", name="uq_findings_run_fingerprint"),
        Index("ix_findings_run_severity", "analysis_run_id", "severity"),
        Index("ix_findings_project_severity", "project_id", "severity"),
    )
