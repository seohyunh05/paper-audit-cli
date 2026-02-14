from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    """
    Project layout (relative to repo root):
      cache/<folder_id>/<file_id>.pdf
      threads/<folder_id>/<file_id>.json   (only papers with issues)
      reports/<folder_id>/summary.json
      reports/summary_all.json
      .secrets/token.json
      credentials.json   (repo root; NOT committed)
    """
    root: Path

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache"

    @property
    def threads_dir(self) -> Path:
        return self.root / "threads"

    @property
    def reports_dir(self) -> Path:
        return self.root / "reports"

    @property
    def secrets_dir(self) -> Path:
        return self.root / ".secrets"

    @property
    def credentials_path(self) -> Path:
        return self.root / "credentials.json"

    @property
    def token_path(self) -> Path:
        return self.secrets_dir / "token.json"

    def cache_pdf_path(self, folder_id: str, file_id: str) -> Path:
        return self.cache_dir / folder_id / f"{file_id}.pdf"

    def thread_path(self, folder_id: str, file_id: str) -> Path:
        return self.threads_dir / folder_id / f"{file_id}.json"

    def folder_report_path(self, folder_id: str) -> Path:
        return self.reports_dir / folder_id / "summary.json"

    def all_report_path(self) -> Path:
        return self.reports_dir / "summary_all.json"


@dataclass
class AuditPolicy:
    # Drive traversal
    recursive: bool = False

    # Basic checks
    min_pages: int = 2
    min_text_chars: int = 500

    # Concurrency
    workers: int = 6
    llm_workers: int = 2  # keep small to reduce rate limiting/cost spikes

    # LLM
    enable_llm: bool = True
    llm_model: str = "gpt-4.1-mini"
    llm_reasoning_effort: str = "low"  # low/medium/high depending on your client impl

    # LLM text chunk limits
    llm_max_chars: int = 120_000

    # Safety/testing
    max_files: int | None = None  # e.g., 5 to test


def apply_quick_mode(policy: AuditPolicy) -> AuditPolicy:
    """
    Optional helper if you later want a "fast scan" mode.
    For now, just returns policy unchanged.
    """
    return policy
