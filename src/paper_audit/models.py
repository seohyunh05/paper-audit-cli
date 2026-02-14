# src/paper_audit/models.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class DriveFile:
    id: str
    name: str
    mime_type: str = "application/pdf"
    modified_time: str | None = None  # RFC3339/ISO string if available

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "mime_type": self.mime_type,
            "modified_time": self.modified_time,
        }


@dataclass
class Issue:
    """
    category: "CRITICAL ERROR" | "INTERMEDIATE ERROR" | "MINOR ERROR" | "SYSTEM"
    """
    category: str
    message: str
    detail: str | None = None
    location: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "message": self.message,
            "detail": self.detail,
            "location": self.location,
        }


@dataclass
class PaperThread:
    thread_id: str
    drive_file: DriveFile
    local_path: str
    issues: list[Issue]
    llm_raw: Any = None

    def has_any_issue(self) -> bool:
        return len(self.issues) > 0

    def has_errors(self) -> bool:
        error_cats = {"SYSTEM", "CRITICAL ERROR", "INTERMEDIATE ERROR"}
        return any(i.category in error_cats for i in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "drive_file": self.drive_file.to_dict(),
            "local_path": self.local_path,
            "issues": [i.to_dict() for i in self.issues],
            "llm_raw": self.llm_raw,
        }
