import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, Text, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base

class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    status = Column(String, nullable=False, default="pending") # pending, processing, completed, failed
    source_type = Column(String, default="zip")
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    summary = Column(JSON, nullable=True)
    tool_versions = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="analyses")
    findings = relationship("Finding", back_populates="analysis_run", cascade="all, delete-orphan")

class Finding(Base):
    __tablename__ = "findings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_run_id = Column(UUID(as_uuid=True), ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False)
    tool = Column(String, nullable=False)
    rule_id = Column(String, nullable=True)
    severity = Column(String, nullable=False)
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    file_path = Column(String, nullable=False)
    line_start = Column(String, nullable=True) # Using string because some tools might provide ranges
    line_end = Column(String, nullable=True)
    fingerprint = Column(String, index=True, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    analysis_run = relationship("AnalysisRun", back_populates="findings")
