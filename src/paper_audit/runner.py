from __future__ import annotations
from pathlib import Path
from typing import Dict
from datetime import datetime
import json

from .config import Paths, AuditPolicy
from .drive_client import list_pdfs_in_folder, download_file
from .models import PaperThread
from .checks import check_pdf_openable, check_basic_content, check_with_llm
from .thread_store import save_thread, delete_thread
from .llm_client import LLMClient, LLMConfig

def audit_folder(paths: Paths, folder_id: str, policy: AuditPolicy) -> Dict:
    paths.cache_dir.mkdir(parents=True, exist_ok=True)
    paths.threads_dir.mkdir(parents=True, exist_ok=True)
    paths.reports_dir.mkdir(parents=True, exist_ok=True)

    pdfs = list_pdfs_in_folder(paths, folder_id, recursive=policy.recursive)
    llm = LLMClient(LLMConfig(model=policy.llm_model, reasoning_effort=policy.llm_reasoning_effort))

    summary = {
        "folder_id": folder_id,
        "scanned_at": datetime.utcnow().isoformat(),
        "total_pdfs": len(pdfs),
        "kept_threads": 0,
        "deleted_threads": 0,
        "papers_with_issues": 0,
        "papers_no_issues": 0,
        "items": []
    }

    for f in pdfs:
        local_path = paths.cache_dir / f"{f.id}.pdf"
        if not local_path.exists():
            download_file(paths, f.id, local_path)

        thread = PaperThread(thread_id=f.id, drive_file=f, local_path=str(local_path))

        thread.issues.extend(check_pdf_openable(local_path))

        if not thread.has_errors():
            thread.issues.extend(check_basic_content(local_path, policy.min_pages, policy.min_text_chars))

        if policy.enable_llm and not thread.has_errors():
            llm_issues, llm_raw = check_with_llm(
                pdf_path=local_path,
                paper_title=f.name,
                llm=llm,
                max_chars=policy.llm_max_chars,
                chunk_chars=policy.llm_chunk_chars,
                overlap=policy.llm_chunk_overlap,
            )
            thread.issues.extend(llm_issues)
            thread.llm_raw = llm_raw

        save_thread(paths.threads_dir, thread)

        if thread.has_any_issue():
            summary["papers_with_issues"] += 1
        else:
            summary["papers_no_issues"] += 1

        if policy.delete_thread_if_no_errors and not thread.has_any_issue():
            delete_thread(paths.threads_dir, thread.thread_id)
            summary["deleted_threads"] += 1
            kept = False

            if policy.delete_cached_pdf_if_no_errors:
                try:
                    Path(thread.local_path).unlink(missing_ok=True)
                except Exception:
                    pass
        else:
            summary["kept_threads"] += 1
            kept = True

        summary["items"].append({
            "fileId": f.id,
            "name": f.name,
            "local_path": str(local_path),
            "issue_count": len(thread.issues),
            "kept_thread": kept
        })

    (paths.reports_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary
