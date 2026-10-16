"""Project table: the unit everything else hangs off (runs → findings)."""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, ForeignKey, JSON, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base import Base

class Project(Base):
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    # Per-project analysis overrides. Validated and clamped server-side against
    # the platform ceiling in app/analysis/config.py before it is ever stored.
    analysis_config = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("User", back_populates="projects")
    # Deleting a project takes its analysis runs (and, through them, findings) with it.
    analyses = relationship("AnalysisRun", back_populates="project", cascade="all, delete-orphan")
