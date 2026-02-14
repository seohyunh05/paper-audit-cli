from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .checks import check_basic_content, check_pdf_openable
from .config import AuditPolicy, apply_quick_mode
from .drive_client import DriveClient
from .llm_client import LLMClient, LLMConfig
from .models import DriveFile, PaperThread, Issue, utc_now_iso
from .prompts import AUDIT_PROMPT
from .text_extract import extract_text
from .thread_store import save_summary, save_thread


class Paths:
    """
    Layout:
      cache/<folder_id>/<file_id>.pdf
      threads/<folder_id>/<file_id>.json
      reports/<folder_id>/summary.json
      reports/summary_all.json
    """
    def __init__(self, root: Path):
        self.root = root
        self.cache_dir = root / "cache"
        self.threads_dir = root / "threads"
        self.reports_dir = root / "reports"
        self.secrets_dir = root / ".secrets"
        self.credentials_path = root / "credentials.json"
        self.token_path = self.secrets_dir / "token.json"

    def cache_pdf_path(self, folder_id: str, file_id: str) -> Path:
        return self.cache_dir / folder_id / f"{file_id}.pdf"

    def thread_path(self, folder_id: str, file_id: str) -> Path:
        return self.threads_dir / folder_id / f"{file_id}.json"

    def folder_report_path(self, folder_id: str) -> Path:
        return self.reports_dir / folder_id / "summary.json"

    def all_report_path(self) -> Path:
        return self.reports_dir / "summary_all.json"


def audit_folders(
    paths: Paths,
    drive: DriveClient,
    folder_ids: list[str],
    policy: AuditPolicy,
) -> dict[str, Any]:
    policy = apply_quick_mode(policy)

    all_summary: dict[str, Any] = {
        "scanned_at": utc_now_iso(),
        "folders": [],
        "total_pdfs": 0,
        "papers_with_issues": 0,
        "papers_no_issues": 0,
        "kept_threads": 0,
        "deleted_threads": 0,
    }

    for folder_id in folder_ids:
        folder_summary = audit_folder(paths, drive, folder_id, policy)
        all_summary["folders"].append(folder_summary)
        all_summary["total_pdfs"] += folder_summary["total_pdfs"]
        all_summary["papers_with_issues"] += folder_summary["papers_with_issues"]
        all_summary["papers_no_issues"] += folder_summary["papers_no_issues"]
        all_summary["kept_threads"] += folder_summary["kept_threads"]
        all_summary["deleted_threads"] += folder_summary["deleted_threads"]

    save_summary(paths.all_report_path(), all_summary)
    return all_summary


def audit_folder(
    paths: Paths,
    drive: DriveClient,
    folder_id: str,
    policy: AuditPolicy,
) -> dict[str, Any]:
    # Ensure base dirs exist
    paths.cache_dir.mkdir(parents=True, exist_ok=True)
    paths.threads_dir.mkdir(parents=True, exist_ok=True)
    paths.reports_dir.mkdir(parents=True, exist_ok=True)

    pdfs = drive.list_pdfs_in_folder(folder_id, recursive=policy.recursive)
    if policy.max_files is not None:
        pdfs = pdfs[: policy.max_files]

    summary: dict[str, Any] = {
        "folder_id": folder_id,
        "scanned_at": utc_now_iso(),
        "total_pdfs": len(pdfs),
        "kept_threads": 0,
        "deleted_threads": 0,
        "papers_with_issues": 0,
        "papers_no_issues": 0,
        "items": [],  # per-pdf mini summary
        "dirs": {
            "cache_dir": str((paths.cache_dir / folder_id).resolve()),
            "threads_dir": str((paths.threads_dir / folder_id).resolve()),
            "report_path": str(paths.folder_report_path(folder_id).resolve()),
        },
    }

    llm: LLMClient | None = None
    if policy.enable_llm:
        llm = LLMClient(LLMConfig(model=policy.llm_model, reasoning_effort=policy.llm_reasoning_effort))

    # ---- Stage 1: ensure local PDFs (download only if needed) ----
    def ensure_local_pdf(f: DriveFile) -> tuple[DriveFile, Path, list[Issue]]:
        local_path = paths.cache_pdf_path(folder_id, f.id)
        try:
            if not DriveClient.local_is_fresh(local_path, f.modified_time):
                drive.download_pdf(f.id, local_path)
            return f, local_path, []
        except Exception as e:
            return f, local_path, [Issue(category="SYSTEM", message="Failed to download PDF", detail=str(e))]

    # ---- Stage 2: basic checks + optional LLM ----
    def process_one(f: DriveFile, local_path: Path, pre_issues: list[Issue]) -> PaperThread:
        issues = list(pre_issues)

        # Basic checks
        issues.extend(check_pdf_openable(local_path))
        if not any(i.category == "SYSTEM" for i in issues):
            issues.extend(check_basic_content(local_path, policy.min_pages, policy.min_text_chars))

        thread = PaperThread(thread_id=f.id, drive_file=f, local_path=str(local_path), issues=issues, llm_raw=None)

        # LLM check: only if enabled and no SYSTEM errors
        if llm is not None and not any(i.category == "SYSTEM" for i in thread.issues):
            try:
                text = extract_text(local_path, max_chars=policy.llm_max_chars)
                llm_issues, llm_raw = llm.audit_text(AUDIT_PROMPT, paper_title=f.name, paper_text=text)
                thread.issues.extend(llm_issues)
                thread.llm_raw = llm_raw
            except Exception as e:
                thread.issues.append(Issue(category="SYSTEM", message="LLM audit failed", detail=str(e)))

        return thread

    # Download in parallel
    downloaded: list[tuple[DriveFile, Path, list[Issue]]] = []
    with ThreadPoolExecutor(max_workers=max(1, policy.workers)) as ex:
        futures = [ex.submit(ensure_local_pdf, f) for f in pdfs]
        for fut in as_completed(futures):
            downloaded.append(fut.result())

    # Basic checks in parallel, LLM in limited parallel
    # We split: do basic processing concurrently, but guard LLM concurrency.
    # For simplicity, we run entire `process_one` in a smaller pool when LLM is enabled.
    max_workers_stage2 = policy.llm_workers if policy.enable_llm else policy.workers
    max_workers_stage2 = max(1, max_workers_stage2)

    threads_out: list[PaperThread] = []
    with ThreadPoolExecutor(max_workers=max_workers_stage2) as ex:
        futures2 = [ex.submit(process_one, f, local_path, pre_issues) for (f, local_path, pre_issues) in downloaded]
        for fut in as_completed(futures2):
            threads_out.append(fut.result())

    # Save threads per folder; delete threads with no issues
    for thread in threads_out:
        thread_path = paths.thread_path(folder_id, thread.thread_id)

        item = {
            "file_id": thread.drive_file.id,
            "name": thread.drive_file.name,
            "local_path": thread.local_path,
            "has_any_issue": thread.has_any_issue(),
            "issue_categories": sorted({i.category for i in thread.issues}),
        }
        summary["items"].append(item)

        if thread.has_any_issue():
            save_thread(thread_path, thread)
            summary["kept_threads"] += 1
            summary["papers_with_issues"] += 1
        else:
            # delete thread file if exists
            if thread_path.exists():
                thread_path.unlink()
            summary["deleted_threads"] += 1
            summary["papers_no_issues"] += 1

    # Save per-folder summary
    save_summary(paths.folder_report_path(folder_id), summary)
    return summary
