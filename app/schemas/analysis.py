from pydantic import BaseModel
from typing import Optional, List
from uuid import UUID
from datetime import datetime

class AnalysisRunResponse(BaseModel):
    id: UUID
    project_id: UUID
    status: str
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    error_message: Optional[str]
    summary: Optional[dict]
    created_at: datetime

    class Config:
        from_attributes = True

class FindingResponse(BaseModel):
    id: UUID
    tool: str
    rule_id: Optional[str]
    severity: str
    title: str
    message: str
    file_path: str
    line_start: Optional[str]
    line_end: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True
