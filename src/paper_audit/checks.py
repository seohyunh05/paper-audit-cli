from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Try to import Issue model from your project.
# If it doesn't exist (or causes circular imports), fall back to a simple Issue dataclass.
try:
    from paper_audit.models import Issue
except Exception:
    @dataclass
    class Issue:
        level: str            # "CRITICAL" | "INTERMEDIATE" | "MINOR"
        code: str             # short machine-readable code
        message: str          # human message
        details: Optional[Dict[str, Any]] = None


# --- PDF helpers -------------------------------------------------------------

def _read_pdf_pages_and_text(pdf_path: Path) -> Tuple[int, str]:
    """
    Returns (num_pages, extracted_text).
    Uses pypdf if available.
    """
    try:
        from pypdf import PdfReader  # pip install pypdf
    except Exception as e:
        raise RuntimeError(
            "Missing dependency 'pypdf'. Install it with: pip install pypdf"
        ) from e

    reader = PdfReader(str(pdf_path))
    num_pages = len(reader.pages)

    texts: List[str] = []
    for p in reader.pages:
        try:
            t = p.extract_text() or ""
        except Exception:
            t = ""
        if t:
            texts.append(t)

    return num_pages, "\n".join(texts)


# --- Checks ------------------------------------------------------------------

def check_pdf_openable(pdf_path: Path) -> List[Issue]:
    """
    Basic sanity check: can we open/parse the PDF at all?
    """
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
        _read_pdf_pages_and_text(pdf_path)
    except Exception as e:
        issues.append(Issue(
            level="CRITICAL",
            code="PDF_UNREADABLE",
            message="PDF could not be opened/parsed (corrupt, encrypted, or unsupported).",
            details={"path": str(pdf_path), "error": str(e)},
        ))
    return issues


def check_basic_content(pdf_path: Path, min_pages: int, min_text_chars: int) -> List[Issue]:
    """
    Checks:
    - minimum page count
    - minimum extracted text length (rough proxy for OCR/scan-only PDFs)
    """
    issues: List[Issue] = []

    try:
        pages, text = _read_pdf_pages_and_text(pdf_path)
    except Exception as e:
        # If it fails here, treat it as unreadable.
        issues.append(Issue(
            level="CRITICAL",
            code="PDF_UNREADABLE",
            message="PDF could not be opened/parsed for content checks.",
            details={"path": str(pdf_path), "error": str(e)},
        ))
        return issues

    if pages < min_pages:
        issues.append(Issue(
            level="MINOR",
            code="TOO_FEW_PAGES",
            message=f"PDF has only {pages} page(s) (< min_pages={min_pages}).",
            details={"pages": pages, "min_pages": min_pages},
        ))

    txt_len = len(text.strip())
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


# --- LLM check ---------------------------------------------------------------

def check_with_llm(
    pdf_path: Path,
    paper_title: str,
    llm: Any,
    max_chars: int = 120_000,
    chunk_chars: int = 20_000,
    overlap: int = 1_000,
) -> Tuple[List[Issue], Dict[str, Any]]:
    """
    Runs the professor's audit prompt against the PDF text.
    Returns (issues, raw_llm_output).

    NOTE: This function assumes your llm client has a method:
        llm.review(text=..., title=...) -> dict with keys:
          - "issues": List[Issue-like dicts or strings]
          - "raw": raw model response
    If your llm client differs, adjust in llm_client.py instead of here.
    """
    # Extract text
    pages, full_text = _read_pdf_pages_and_text(pdf_path)
    text = full_text.strip()

    # Truncate to max_chars (LLM cost control)
    if len(text) > max_chars:
        text = text[:max_chars]

    # Simple chunking (optional). If you prefer single-shot, just send `text`.
    chunks: List[str] = []
    if len(text) <= chunk_chars:
        chunks = [text]
    else:
        i = 0
        while i < len(text):
            chunks.append(text[i:i + chunk_chars])
            i += max(1, chunk_chars - overlap)

    all_issues: List[Issue] = []
    raw: Dict[str, Any] = {"pages": pages, "chunks": len(chunks), "responses": []}

    for idx, c in enumerate(chunks, start=1):
        resp = llm.review(text=c, title=paper_title)
        raw["responses"].append({"chunk": idx, "resp": resp})

        # Normalize issues from response
        resp_issues = resp.get("issues", [])
        for it in resp_issues:
            if isinstance(it, Issue):
                all_issues.append(it)
            elif isinstance(it, dict):
                all_issues.append(Issue(
                    level=str(it.get("level", "INTERMEDIATE")).upper(),
                    code=str(it.get("code", "LLM_FLAG")),
                    message=str(it.get("message", ""))[:2000],
                    details=it.get("details"),
                ))
            else:
                all_issues.append(Issue(
                    level="INTERMEDIATE",
                    code="LLM_FLAG",
                    message=str(it)[:2000],
                    details={"chunk": idx},
                ))

    return all_issues, raw
