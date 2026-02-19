from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from paper_audit.config import AuditPolicy, Paths
from paper_audit.drive_client import list_pdfs_in_folder, download_file
from paper_audit.checks import (
    check_pdf_openable,
    read_pdf_pages_and_text,
    check_basic_content_from_extracted,
    check_with_llm_from_extracted,
)
from paper_audit.llm_client import LLMClient, LLMConfig
from paper_audit.models import DriveFile, PaperThread, Issue
from paper_audit.thread_store import save_thread, save_summary


def _load_meta(meta_path: Path) -> Optional[Dict[str, Any]]:
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_meta(meta_path: Path, meta: Dict[str, Any]) -> None:
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_unchanged(f: DriveFile, meta: Optional[Dict[str, Any]]) -> bool:
    if not meta:
        return False
    return (meta.get("modified_time") == f.modified_time) and (meta.get("size") == f.size)


def _ensure_local_pdf(paths: Paths, f: DriveFile, *, force_redownload: bool) -> Path:
    local_path = paths.cache_dir / f"{f.id}.pdf"
    if force_redownload and local_path.exists():
        try:
            local_path.unlink()
        except Exception:
            pass
    if not local_path.exists():
        download_file(paths, f.id, local_path)
    return local_path


def audit_folder(paths: Paths, folder_id: str, policy: AuditPolicy) -> Dict[str, Any]:
    paths.cache_dir.mkdir(parents=True, exist_ok=True)
    paths.threads_dir.mkdir(parents=True, exist_ok=True)
    paths.reports_dir.mkdir(parents=True, exist_ok=True)

    pdfs: List[DriveFile] = list_pdfs_in_folder(paths, folder_id, recursive=policy.recursive)

    if policy.max_files is not None:
        pdfs = pdfs[: int(policy.max_files)]

    llm: Optional[LLMClient] = None
    if policy.enable_llm:
        llm = LLMClient(LLMConfig(model=policy.llm_model))

    summary: Dict[str, Any] = {
        "folder_id": folder_id,
        "scanned_at": datetime.utcnow().isoformat(),
        "total_pdfs": len(pdfs),
        "kept_threads": 0,
        "deleted_threads": 0,
        "papers_with_issues": 0,
        "papers_no_issues": 0,
        "skipped_unchanged": 0,
        "items": [],
    }

    if not pdfs:
        save_summary(paths.reports_dir / "summary.json", summary)
        return summary

    id_to_rank = {f.id: i for i, f in enumerate(pdfs)}

    # Decide what to skip BEFORE downloading
    to_process: List[DriveFile] = []
    skipped: List[DriveFile] = []

    for f in pdfs:
        meta = _load_meta(paths.meta_path(f.id))
        if policy.skip_unchanged and not policy.force_recheck and _is_unchanged(f, meta):
            skipped.append(f)
        else:
            to_process.append(f)

    summary["skipped_unchanged"] = len(skipped)

    # If everything is unchanged and we’re skipping unchanged, just write summary quickly.
    if not to_process:
        for f in skipped:
            summary["items"].append({
                "file_id": f.id,
                "file_name": f.name,
                "local_path": str(paths.cache_dir / f"{f.id}.pdf"),
                "has_issues": None,   # unknown here unless you read old thread files
                "num_issues": None,
                "skipped": True,
            })
        save_summary(paths.reports_dir / "summary.json", summary)
        return summary

    # -------------------------
    # Stage 1: Download in parallel
    # -------------------------
    downloaded: List[Tuple[DriveFile, Path]] = []
    with ThreadPoolExecutor(max_workers=max(1, policy.download_workers)) as ex:
        futs = {
            ex.submit(_ensure_local_pdf, paths, f, force_redownload=policy.force_redownload): f
            for f in to_process
        }
        for fut in as_completed(futs):
            f = futs[fut]
            local_path = fut.result()
            downloaded.append((f, local_path))

    downloaded.sort(key=lambda t: id_to_rank.get(t[0].id, 10**9))

    # -------------------------
    # Stage 2: Extract ONCE + Basic checks in parallel
    # -------------------------
    def _basic_stage(f: DriveFile, local_path: Path) -> Tuple[DriveFile, Path, int, str, List[Issue]]:
        issues: List[Issue] = []
        issues.extend(check_pdf_openable(local_path))
        if issues:
            return (f, local_path, 0, "", issues)

        try:
            pages, text = read_pdf_pages_and_text(local_path)
        except Exception as e:
            issues.append(Issue(
                level="CRITICAL",
                code="PDF_UNREADABLE",
                message="PDF could not be opened/parsed for text extraction.",
                details={"path": str(local_path), "error": str(e)},
            ))
            return (f, local_path, 0, "", issues)

        issues.extend(check_basic_content_from_extracted(
            pages=pages,
            text=text,
            min_pages=policy.min_pages,
            min_text_chars=policy.min_text_chars,
        ))
        return (f, local_path, pages, text, issues)

    processed: List[Tuple[DriveFile, Path, int, str, List[Issue], Optional[Dict[str, Any]]]] = []
    with ThreadPoolExecutor(max_workers=max(1, policy.workers)) as ex:
        futs2 = {ex.submit(_basic_stage, f, lp): (f, lp) for (f, lp) in downloaded}
        for fut in as_completed(futs2):
            f2, lp2, pages, text, basic_issues = fut.result()
            processed.append((f2, lp2, pages, text, basic_issues, None))

    processed.sort(key=lambda t: id_to_rank.get(t[0].id, 10**9))

    # -------------------------
    # Stage 3: LLM checks (optional; usually slow)
    # Uses the already-extracted text.
    # -------------------------
    if policy.enable_llm and llm is not None:
        llm_targets = [(f, pages, text) for (f, _lp, pages, text, issues, _raw) in processed if len(issues) == 0]

        def _llm_one(f: DriveFile, pages: int, text: str) -> Tuple[str, List[Issue], Dict[str, Any]]:
            llm_issues, llm_raw = check_with_llm_from_extracted(
                pages=pages,
                text=text,
                paper_title=f.name,
                llm=llm,
                max_chars=policy.llm_max_chars,
                chunk_chars=policy.llm_chunk_chars,
                overlap=policy.llm_chunk_overlap,
            )
            return (f.id, llm_issues, llm_raw)

        id_to_llm: Dict[str, Tuple[List[Issue], Dict[str, Any]]] = {}
        with ThreadPoolExecutor(max_workers=max(1, policy.llm_workers)) as ex:
            futs3 = {ex.submit(_llm_one, f, pages, text): f.id for (f, pages, text) in llm_targets}
            for fut in as_completed(futs3):
                fid2, llm_issues, llm_raw = fut.result()
                id_to_llm[fid2] = (llm_issues, llm_raw)

        merged = []
        for (f, lp, pages, text, issues, _raw) in processed:
            if f.id in id_to_llm:
                llm_issues, llm_raw = id_to_llm[f.id]
                merged.append((f, lp, pages, text, issues + llm_issues, llm_raw))
            else:
                merged.append((f, lp, pages, text, issues, None))
        processed = merged

    # -------------------------
    # Save outputs + write meta (so next scan can skip unchanged)
    # -------------------------
    for (f, local_path, _pages, _text, issues, llm_raw) in processed:
        thread = PaperThread(
            thread_id=f.id,
            drive_file=f,
            local_path=str(local_path),
            issues=issues,
            llm_raw=llm_raw,
        )

        summary["items"].append({
            "file_id": f.id,
            "file_name": f.name,
            "local_path": str(local_path),
            "has_issues": thread.has_any_issue(),
            "num_issues": len(thread.issues),
            "skipped": False,
        })

        if thread.has_any_issue():
            save_thread(paths.thread_path(folder_id, thread.thread_id), thread)
            summary["kept_threads"] += 1
            summary["papers_with_issues"] += 1
        else:
            summary["deleted_threads"] += 1
            summary["papers_no_issues"] += 1

        _save_meta(paths.meta_path(f.id), {
            "file_id": f.id,
            "modified_time": f.modified_time,
            "size": f.size,
            "cached_pdf": str(local_path),
            "last_scanned_at": datetime.utcnow().isoformat(),
            "had_issues": thread.has_any_issue(),
            "num_issues": len(thread.issues),
        })

    # Add skipped items to summary list (optional reporting)
    for f in skipped:
        summary["items"].append({
            "file_id": f.id,
            "file_name": f.name,
            "local_path": str(paths.cache_dir / f"{f.id}.pdf"),
            "has_issues": None,
            "num_issues": None,
            "skipped": True,
        })

    save_summary(paths.reports_dir / "summary.json", summary)
    return summary
