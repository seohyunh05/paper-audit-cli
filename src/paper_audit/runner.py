from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .checks import check_basic_content, check_pdf_openable
from .config import AuditPolicy, Paths, apply_quick_mode
from .drive_client import DriveClient
from .llm_client import LLMClient, LLMConfig
from .models import DriveFile, Issue, PaperThread, utc_now_iso
from .prompts import AUDIT_PROMPT
from .text_extract import extract_text
from .thread_store import save_summary, save_thread


def audit_folder(paths: Paths, drive: DriveClient, folder_id: str, policy: AuditPolicy) -> dict[str, Any]:
    policy = apply_quick_mode(policy)

    # Ensure base dirs exist
    paths.cache_dir.mkdir(parents=True, exist_ok=True)
    paths.threads_dir.mkdir(parents=True, exist_ok=True)
    paths.reports_dir.mkdir(parents=True, exist_ok=True)

    pdfs: list[DriveFile] = drive.list_pdfs_in_folder(folder_id, recursive=policy.recursive)
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
        "items": [],
        "dirs": {
            "cache_dir": str((paths.cache_dir / folder_id).resolve()),
            "threads_dir": str((paths.threads_dir / folder_id).resolve()),
            "report_path": str(paths.folder_report_path(folder_id).resolve()),
        },
    }

    llm: LLMClient | None = None
    if policy.enable_llm:
        llm = LLMClient(LLMConfig(model=policy.llm_model, reasoning_effort=policy.llm_reasoning_effort))

    # ---------- Stage 1: ensure local PDFs (download only if needed) ----------
    def ensure_local_pdf(f: DriveFile) -> tuple[DriveFile, Path, list[Issue]]:
        local_path = paths.cache_pdf_path(folder_id, f.id)
        try:
            if not DriveClient.local_is_fresh(local_path, f.modified_time):
                drive.download_pdf(f.id, local_path)
            return f, local_path, []
        except Exception as e:
            return f, local_path, [Issue(category="SYSTEM", message="Failed to download PDF", detail=str(e))]

    # ---------- Stage 2: checks + optional LLM ----------
    def process_one(f: DriveFile, local_path: Path, pre_issues: list[Issue]) -> PaperThread:
        issues: list[Issue] = list(pre_issues)

        # Basic checks
        issues.extend(check_pdf_openable(local_path))
        if not any(i.category == "SYSTEM" for i in issues):
            issues.extend(check_basic_content(local_path, policy.min_pages, policy.min_text_chars))

        thread = PaperThread(thread_id=f.id, drive_file=f, local_path=str(local_path), issues=issues, llm_raw=None)

        # LLM audit only if enabled + no SYSTEM errors
        if llm is not None and not any(i.category == "SYSTEM" for i in thread.issues):
            try:
                text = extract_text(local_path, max_chars=policy.llm_max_chars)
                llm_issues, llm_raw = llm.audit_text(
                    system_prompt=AUDIT_PROMPT,
                    paper_title=f.name,
                    paper_text=text,
                )
                thread.issues.extend(llm_issues)
                thread.llm_raw = llm_raw
            except Exception as e:
                thread.issues.append(Issue(category="SYSTEM", message="LLM audit failed", detail=str(e)))

        return thread

    # ---------- Run Stage 1 in parallel ----------
    downloaded: list[tuple[DriveFile, Path, list[Issue]]] = []
    with ThreadPoolExecutor(max_workers=max(1, policy.workers)) as ex:
        futures = [ex.submit(ensure_local_pdf, f) for f in pdfs]
        for fut in as_completed(futures):
            downloaded.append(fut.result())

    # ---------- Run Stage 2 ----------
    # If LLM enabled, keep concurrency smaller
    max_workers_stage2 = policy.llm_workers if policy.enable_llm else policy.workers
    max_workers_stage2 = max(1, max_workers_stage2)

    threads_out: list[PaperThread] = []
    with ThreadPoolExecutor(max_workers=max_workers_stage2) as ex:
        futures2 = [ex.submit(process_one, f, lp, pre) for (f, lp, pre) in downloaded]
        for fut in as_completed(futures2):
            threads_out.append(fut.result())

    # ---------- Save outputs per folder ----------
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
            if thread_path.exists():
                thread_path.unlink()
            summary["deleted_threads"] += 1
            summary["papers_no_issues"] += 1

    save_summary(paths.folder_report_path(folder_id), summary)
    return summary
