from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional


@dataclass
class DriveFile:
    id: str
    name: str
    mime_type: str
    modified_time: Optional[str] = None  # from Drive API
    size: Optional[int] = None           # bytes (Drive returns as string; we can cast)


@dataclass
class Issue:
    level: str            # "CRITICAL" | "INTERMEDIATE" | "MINOR"
    code: str             # short machine-readable code
    message: str          # human message
    details: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PaperThread:
    thread_id: str
    drive_file: DriveFile
    local_path: str
    issues: List[Issue]
    llm_raw: Optional[Dict[str, Any]] = None

    def has_errors(self) -> bool:
        return any(i.level.upper() == "CRITICAL" for i in self.issues)

    def has_any_issue(self) -> bool:
        return len(self.issues) > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "drive_file": asdict(self.drive_file),
            "local_path": self.local_path,
            "issues": [i.to_dict() for i in self.issues],
            "llm_raw": self.llm_raw,
        }
