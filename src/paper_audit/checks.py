from __future__ import annotations
from pathlib import Path
from typing import List, Optional

from pypdf import PdfReader

from .models import Issue
from .text_extract import extract_text, chunk_text
from .prompts import REVIEWER_PROMPT, build_user_payload
from .llm_client import LLMClient
from .parse_llm_output import issues_from_llm_output

def check_pdf_openable(pdf_path: Path) -> List[Issue]:
    issues: List[Issue] = []
    try:
        reader = PdfReader(str(pdf_path))
        if reader.is_encrypted:
            issues.append(Issue(
                code="PDF_ENCRYPTED",
                message="PDF is encrypted/locked and cannot be processed without a password.",
                severity="error",
                category="INTERMEDIATE"
            ))
            return issues

        _ = len(reader.pages)
    except Exception as e:
        issues.append(Issue(
            code="PDF_PARSE_FAIL",
            message=f"Failed to open/parse PDF: {type(e).__name__}: {e}",
            severity="error",
            category="INTERMEDIATE"
        ))
    return issues

def _extract_text_len(pdf_path: Path) -> int:
    reader = PdfReader(str(pdf_path))
    total = 0
    for p in reader.pages:
        try:
            t = p.extract_text() or ""
        except Exception:
            t = ""
        total += len(t.strip())
    return total

def check_basic_content(pdf_path: Path, min_pages: int, min_text_chars: int) -> List[Issue]:
    issues: List[Issue] = []
    reader = PdfReader(str(pdf_path))

    n_pages = len(reader.pages)
    if n_pages < min_pages:
        issues.append(Issue(
            code="LOW_PAGE_COUNT",
            message=f"PDF has only {n_pages} page(s). Expected at least {min_pages}.",
            severity="warning",
            category="MINOR",
            meta={"pages": str(n_pages)}
        ))

    txt_len = _extract_text_len(pdf_path)
    if txt_len < min_text_chars:
        issues.append(Issue(
            code="LOW_EXTRACTED_TEXT",
            message=f"Extracted text length is very low ({txt_len} chars). Might be scanned or extraction failure.",
            severity="warning",
            category="MINOR",
            meta={"text_chars": str(txt_len)}
        ))

    return issues

def check_with_llm(
    pdf_path: Path,
    paper_title: str,
    llm: LLMClient,
    max_chars: int,
    chunk_chars: int,
    overlap: int
) -> tuple[list[Issue], Optional[str]]:
    if not llm.available():
        return [], None

    text = extract_text(pdf_path, max_chars=max_chars)
    chunks = chunk_text(text, chunk_chars=chunk_chars, overlap=overlap)
    if not chunks:
        # Keep thread if LLM couldn't read any text
        return [Issue(
            code="NO_TEXT_FOR_LLM",
            message="Could not extract enough text from PDF to run LLM audit.",
            severity="warning",
            category="MINOR"
        )], None

    outputs: List[str] = []
    all_issues: List[Issue] = []

    total = len(chunks)
    for i, ch in enumerate(chunks, start=1):
        user_content = build_user_payload(paper_title=paper_title, chunk_index=i, chunk_total=total, text_chunk=ch)
        out = llm.review(system_prompt=REVIEWER_PROMPT, user_content=user_content)
        outputs.append(out)
        all_issues.extend(issues_from_llm_output(out))

    combined = "\n\n---\n\n".join(outputs)
    return all_issues, combined
