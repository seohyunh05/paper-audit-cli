from __future__ import annotations
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from datetime import datetime

class DriveFile(BaseModel):
    id: str
    name: str
    mimeType: str
    modifiedTime: Optional[str] = None
    size: Optional[str] = None

class Issue(BaseModel):
    code: str
    message: str
    severity: str = Field(default="error")      # error | warning
    category: str = Field(default="INTERMEDIATE")  # CRITICAL | INTERMEDIATE | MINOR
    meta: Dict[str, str] = Field(default_factory=dict)

class PaperThread(BaseModel):
    thread_id: str
    drive_file: DriveFile
    local_path: str
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    issues: List[Issue] = Field(default_factory=list)
    llm_raw: Optional[str] = None

    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)

    def has_any_issue(self) -> bool:
        return len(self.issues) > 0
