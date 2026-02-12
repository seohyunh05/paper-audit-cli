from __future__ import annotations
from pathlib import Path
import json
from .models import PaperThread

def thread_path(threads_dir: Path, thread_id: str) -> Path:
    return threads_dir / f"{thread_id}.json"

def save_thread(threads_dir: Path, thread: PaperThread) -> Path:
    threads_dir.mkdir(parents=True, exist_ok=True)
    p = thread_path(threads_dir, thread.thread_id)
    p.write_text(thread.model_dump_json(indent=2), encoding="utf-8")
    return p

def delete_thread(threads_dir: Path, thread_id: str) -> None:
    p = thread_path(threads_dir, thread_id)
    if p.exists():
        p.unlink()

def load_thread(threads_dir: Path, thread_id: str) -> PaperThread:
    p = thread_path(threads_dir, thread_id)
    data = json.loads(p.read_text(encoding="utf-8"))
    return PaperThread(**data)
