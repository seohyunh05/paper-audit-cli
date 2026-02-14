from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuditPolicy:
    # Drive traversal
    recursive: bool = False

    # Basic PDF checks
    min_pages: int = 2
    min_text_chars: int = 800

    # Performance
    workers: int = 6              # parallelism for download + basic checks
    llm_workers: int = 1          # keep small; LLM is slow + can rate limit
    max_files: int | None = None  # for testing: limit number of PDFs per folder

    # LLM
    enable_llm: bool = True
    llm_model: str = "gpt-4.1-mini"
    llm_reasoning_effort: str = "low"

    # Limit text sent to LLM (speed + cost)
    llm_max_chars: int = 12000
    llm_chunk_chars: int = 4000
    llm_chunk_overlap: int = 300

    # Quick mode (faster/cheaper LLM): fewer chars + fewer chunks
    quick_mode: bool = False


def apply_quick_mode(policy: AuditPolicy) -> AuditPolicy:
    if not policy.quick_mode:
        return policy
    # Override for fast testing
    return AuditPolicy(
        recursive=policy.recursive,
        min_pages=policy.min_pages,
        min_text_chars=policy.min_text_chars,
        workers=policy.workers,
        llm_workers=policy.llm_workers,
        max_files=policy.max_files,
        enable_llm=policy.enable_llm,
        llm_model=policy.llm_model,
        llm_reasoning_effort=policy.llm_reasoning_effort,
        llm_max_chars=6000,
        llm_chunk_chars=3000,
        llm_chunk_overlap=200,
        quick_mode=True,
    )
