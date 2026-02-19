from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class Paths:
    """
    Project paths rooted at the repo folder (current working directory).
    """
    root: Path
    secrets_dir: Path
    token_path: Path
    credentials_path: Path
    cache_dir: Path
    threads_dir: Path
    reports_dir: Path

    @staticmethod
    def from_cwd() -> "Paths":
        root = Path.cwd()
        secrets_dir = root / ".secrets"
        token_path = secrets_dir / "token.json"
        credentials_path = root / "credentials.json"
        cache_dir = root / "cache"
        threads_dir = root / "threads"
        reports_dir = root / "reports"
        return Paths(
            root=root,
            secrets_dir=secrets_dir,
            token_path=token_path,
            credentials_path=credentials_path,
            cache_dir=cache_dir,
            threads_dir=threads_dir,
            reports_dir=reports_dir,
        )

    def thread_path(self, folder_id: str, thread_id: str) -> Path:
        safe_folder = (folder_id or "").replace("/", "_")
        safe_thread = (thread_id or "").replace("/", "_")
        return self.threads_dir / safe_folder / f"{safe_thread}.json"

    def meta_path(self, file_id: str) -> Path:
        return self.cache_dir / f"{file_id}.meta.json"


@dataclass
class AuditPolicy:
    recursive: bool = False
    enable_llm: bool = True

    # limits
    max_files: Optional[int] = None

    # concurrency
    workers: int = 6
    download_workers: int = 4
    llm_workers: int = 1

    # incremental speed-up
    skip_unchanged: bool = True   # <-- big win for large folders after first scan
    force_redownload: bool = False
    force_recheck: bool = False   # re-run checks even if unchanged

    # basic checks
    min_pages: int = 1
    min_text_chars: int = 200

    # LLM
    llm_model: str = "gpt-4.1-mini"

    # cost/speed controls for llm check
    llm_max_chars: int = 120_000
    llm_chunk_chars: int = 20_000
    llm_chunk_overlap: int = 1_000
