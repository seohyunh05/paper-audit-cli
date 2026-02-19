from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from paper_audit.models import Issue


def read_pdf_pages_and_text(pdf_path: Path) -> Tuple[int, str]:
    try:
        from pypdf import PdfReader
    except Exception as e:
        raise RuntimeError("Missing dependency 'pypdf'. Install it with: pip install pypdf") from e

    reader = PdfReader(str(pdf_path))
    num_pages = len(reader.pages)

    parts: List[str] = []
    for p in reader.pages:
        try:
            t = p.extract_text() or ""
        except Exception:
            t = ""
        if t:
            parts.append(t)
    return num_pages, "\n".join(parts)


def check_pdf_openable(pdf_path: Path) -> List[Issue]:
    issues: List[Issue] = []
    if not pdf_path.exists():
        issues.append(Issue(
            level="CRITICAL",
            code="PDF_NOT_FOUND",
            message=f"PDF file not found: {pdf_path}",
            details={"path": str(pdf_path)},
        ))
        return issues

    try:
        from pypdf import PdfReader
        _ = PdfReader(str(pdf_path))
    except Exception as e:
        issues.append(Issue(
            level="CRITICAL",
            code="PDF_UNREADABLE",
            message="PDF could not be opened/parsed (corrupt, encrypted, or unsupported).",
            details={"path": str(pdf_path), "error": str(e)},
        ))
    return issues


def check_basic_content_from_extracted(
    *,
    pages: int,
    text: str,
    min_pages: int,
    min_text_chars: int,
) -> List[Issue]:
    issues: List[Issue] = []

    if pages < min_pages:
        issues.append(Issue(
            level="MINOR",
            code="TOO_FEW_PAGES",
            message=f"PDF has only {pages} page(s) (< min_pages={min_pages}).",
            details={"pages": pages, "min_pages": min_pages},
        ))

    txt_len = len((text or "").strip())
    if txt_len < min_text_chars:
        issues.append(Issue(
            level="INTERMEDIATE",
            code="LOW_EXTRACTED_TEXT",
            message=(
                f"Extracted text is very short ({txt_len} chars < min_text_chars={min_text_chars}). "
                "The PDF may be scanned/OCR-only or text extraction may be failing."
            ),
            details={"text_chars": txt_len, "min_text_chars": min_text_chars},
        ))

    return issues


def _chunk_text(text: str, *, chunk_chars: int, overlap: int) -> List[str]:
    text = (text or "").strip()
    if not text:
        return [""]
    if len(text) <= chunk_chars:
        return [text]

    chunks: List[str] = []
    i = 0
    step = max(1, chunk_chars - max(0, overlap))
    while i < len(text):
        chunks.append(text[i:i + chunk_chars])
        i += step
    return chunks


def check_with_llm_from_extracted(
    *,
    pages: int,
    text: str,
    paper_title: str,
    llm: Any,
    system_prompt: Optional[str] = None,
    max_chars: int = 120_000,
    chunk_chars: int = 20_000,
    overlap: int = 1_000,
) -> Tuple[List[Issue], Dict[str, Any]]:
    text = (text or "").strip()
    if len(text) > max_chars:
        text = text[:max_chars]

    chunks = _chunk_text(text, chunk_chars=chunk_chars, overlap=overlap)

    from paper_audit.parse_llm_output import parse_llm_findings
    from paper_audit.prompts import ROLE_PROMPT, build_user_prompt

    sys_prompt = system_prompt or ROLE_PROMPT

    all_issues: List[Issue] = []
    raw: Dict[str, Any] = {"pages": pages, "chunks": len(chunks), "responses": []}

    for idx, c in enumerate(chunks, start=1):
        user_prompt = build_user_prompt(paper_title, c)
        resp = llm.review(content=user_prompt, system_prompt=sys_prompt)

        out_text = resp.get("output_text", "") if isinstance(resp, dict) else str(resp)
        raw["responses"].append({"chunk": idx, "output_text": out_text})

        parsed = parse_llm_findings(out_text)
        for issue in parsed:
            issue.details = {**(issue.details or {}), "chunk": idx}
            all_issues.append(issue)

    return all_issues, raw
