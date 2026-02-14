from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import PaperThread


def save_thread(thread_path: Path, thread: PaperThread) -> None:
    thread_path.parent.mkdir(parents=True, exist_ok=True)
    thread_path.write_text(json.dumps(thread.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def save_summary(summary_path: Path, summary: dict[str, Any]) -> None:
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
