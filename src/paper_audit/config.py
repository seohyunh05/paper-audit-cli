from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Paths:
    root: Path = Path(".")
    secrets_dir: Path = Path(".secrets")
    token_path: Path = Path(".secrets/token.json")
    credentials_path: Path = Path("credentials.json")

    cache_dir: Path = Path("cache")
    threads_dir: Path = Path("threads")
    reports_dir: Path = Path("reports")

@dataclass(frozen=True)
class AuditPolicy:
    recursive: bool = True

    # Basic PDF sanity checks
    min_pages: int = 2
    min_text_chars: int = 300

    # LLM prompt checks
    enable_llm: bool = True
    llm_model: str = "gpt-5"
    llm_reasoning_effort: str = "low"  # low | medium | high (if supported)
    llm_max_chars: int = 120_000
    llm_chunk_chars: int = 18_000
    llm_chunk_overlap: int = 800

    # Storage behavior
    delete_thread_if_no_errors: bool = True
    delete_cached_pdf_if_no_errors: bool = False
