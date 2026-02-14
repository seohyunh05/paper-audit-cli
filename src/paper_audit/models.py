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
    modified_time: str | None = None  # ISO string if available


@dataclass
class Issue:
    """
    category: "CRITICAL ERROR" | "INTERMEDIATE ERROR" | "MINOR ERROR" | "SYSTEM"
    message: short summary
    detail: longer details (optional)
    """
    category: str
    message: str
    detail: str | None = None
    location: str | None = None  # optional (e.g., "Eq (12)", "Page 4, line 3")


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
        # Treat SYSTEM/CRITICAL/INTERMEDIATE as “errors” that prevent auto-delete
        error_cats = {"SYSTEM", "CRITICAL ERROR", "INTERMEDIATE ERROR"}
        return any(i.category in error_cats for i in self.issues)
