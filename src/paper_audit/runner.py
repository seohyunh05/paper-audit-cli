from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from paper_audit.config import AuditPolicy, Paths
from paper_audit.drive_client import (
    list_pdfs_in_folder,
    download_file,
)
from paper_audit.checks import (
    check_pdf_openable,
    check_basic_content,
    check_with_llm,
)
from paper_audit.llm_client import LLMClient, LLMConfig
from paper_audit.models import DriveFile, PaperThread
from paper_audit.thread_store import save_thread, save_summary


def _ensure_local_pdf(paths: Paths, f: DriveFile) -> Path:
    """
    Download PDF from Drive into cache if not already present.
    Returns local path to the cached file.
    """
    local_path = paths.cache_dir / f"{f.id}.pdf"
    if not local_path.exists():
        download_file(paths, f.id, local_path)
    return local_path


def audit_folder(
    paths: Paths,
    folder_id: str,
    policy: AuditPolicy,
) -> Dict[str, Any]:
    """
    Audit all PDFs in a Drive folder.

    Pipeline:
    1) List PDFs
    2) Download PDFs (parallel)
    3) Run basic checks (parallel)
    4) Run LLM check (optional; controlled by policy.enable_llm)
    5) Save per-paper thread JSON for papers with issues; optionally delete/skip threads for clean papers
    6) Save summary.json report
    """
    # Ensure output dirs exist
    paths.cache_dir.mkdir(parents=True, exist_ok=True)
    paths.threads_dir.mkdir(parents=True, exist_ok=True)
    paths.reports_dir.mkdir(parents=True, exist_ok=True)

    # List PDFs
    pdfs: List[DriveFile] = list_pdfs_in_folder(paths, folder_id, recursive=policy.recursive)

    # Apply max_files limit
    if policy.max_files is not None:
        pdfs = pdfs[: int(policy.max_files)]

    # Prepare LLM client if enabled
    llm: Optional[LLMClient] = None
    if policy.enable_llm:
        # IMPORTANT: reasoning_effort is handled safely inside LLMClient (won’t be sent if unsupported)
        llm = LLMClient(LLMConfig(model=policy.llm_model))

    summary: Dict[str, Any] = {
        "folder_id": folder_id,
        "scanned_at": datetime.utcnow().isoformat(),
        "total_pdfs": len(pdfs),
        "kept_threads": 0,
        "deleted_threads": 0,  # in our implementation, "deleted" means "not written"
        "papers_with_issues": 0,
        "papers_no_issues": 0,
        "items": [],
    }

    # -------------------------
    # Stage 1: Download in parallel
    # -------------------------
    downloaded: List[Tuple[DriveFile, Path]] = []
    if len(pdfs) == 0:
        save_summary(paths.reports_dir / "summary.json", summary)
        return summary

    download_workers = max(1, policy.download_workers)
    with ThreadPoolExecutor(max_workers=download_workers) as ex:
        futs = {ex.submit(_ensure_local_pdf, paths, f): f for f in pdfs}
        for fut in as_completed(futs):
            f = futs[fut]
            local_path = fut.result()
            downloaded.append((f, local_path))

    # Keep stable order for readability (by original listing order)
    id_to_rank = {f.id: i for i, f in enumerate(pdfs)}
    downloaded.sort(key=lambda t: id_to_rank.get(t[0].id, 10**9))

    # -------------------------
    # Stage 2: Basic checks in parallel (fast)
    # -------------------------
    def _basic_checks(f: DriveFile, local_path: Path) -> Tuple[DriveFile, Path, List[Dict[str, Any]]]:
        issues: List[Dict[str, Any]] = []
        issues.extend(check_pdf_openable(local_path))
        if not issues:
            issues.extend(check_basic_content(local_path, policy.min_pages, policy.min_text_chars))
        return (f, local_path, issues)

    processed: List[Tuple[DriveFile, Path, List[Dict[str, Any]], Optional[str]]] = []
    # last element is optional llm_raw text

    basic_workers = max(1, policy.workers)
    with ThreadPoolExecutor(max_workers=basic_workers) as ex:
        futs2 = {ex.submit(_basic_checks, f, lp): (f, lp) for (f, lp) in downloaded}
        for fut in as_completed(futs2):
            f, lp = futs2[fut]
            f2, lp2, basic_issues = fut.result()
            processed.append((f2, lp2, basic_issues, None))

    processed.sort(key=lambda t: id_to_rank.get(t[0].id, 10**9))

    # -------------------------
    # Stage 3: LLM checks (optional, usually slow) — limited concurrency
    # -------------------------
    if policy.enable_llm and llm is not None:
        llm_workers = max(1, policy.llm_workers)

        def _llm_check_one(f: DriveFile, local_path: Path) -> Tuple[str, List[Dict[str, Any]], str]:
            llm_issues, llm_raw = check_with_llm(
                pdf_path=local_path,
                paper_title=f.name,
                llm=llm,
                max_chars=policy.llm_max_chars,
                chunk_chars=policy.llm_chunk_chars,
                overlap=policy.llm_chunk_overlap,
            )
            return (f.id, llm_issues, llm_raw)

        # Only run LLM if basic checks passed (no errors)
        llm_targets = [(f, lp) for (f, lp, issues, _) in processed if len(issues) == 0]

        id_to_llm: Dict[str, Tuple[List[Dict[str, Any]], str]] = {}
        with ThreadPoolExecutor(max_workers=llm_workers) as ex:
            futs3 = {ex.submit(_llm_check_one, f, lp): f.id for (f, lp) in llm_targets}
            for fut in as_completed(futs3):
                fid = futs3[fut]
                fid2, llm_issues, llm_raw = fut.result()
                id_to_llm[fid2] = (llm_issues, llm_raw)

        # merge back
        new_processed: List[Tuple[DriveFile, Path, List[Dict[str, Any]], Optional[str]]] = []
        for (f, lp, issues, _) in processed:
            if f.id in id_to_llm:
                llm_issues, llm_raw = id_to_llm[f.id]
                issues = issues + llm_issues
                new_processed.append((f, lp, issues, llm_raw))
            else:
                new_processed.append((f, lp, issues, None))
        processed = new_processed

    # -------------------------
    # Save outputs
    # -------------------------
    for (f, local_path, issues, llm_raw) in processed:
        thread = PaperThread(
            thread_id=f.id,
            drive_file=f,
            local_path=str(local_path),
            issues=issues,
            llm_raw=llm_raw,
        )

        item = {
            "file_id": f.id,
            "file_name": f.name,
            "local_path": str(local_path),
            "has_issues": thread.has_any_issue(),
            "num_issues": len(thread.issues),
        }
        summary["items"].append(item)

        if thread.has_any_issue():
            # Save thread JSON for papers with issues
            thread_path = paths.thread_path(folder_id, thread.thread_id)
            save_thread(thread_path, thread)
            summary["kept_threads"] += 1
            summary["papers_with_issues"] += 1
        else:
            # No issues: don’t write a thread file (acts like “auto delete”)
            summary["deleted_threads"] += 1
            summary["papers_no_issues"] += 1

    # Save summary
    save_summary(paths.reports_dir / "summary.json", summary)
    return summary
