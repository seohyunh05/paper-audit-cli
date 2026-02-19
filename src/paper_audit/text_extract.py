from __future__ import annotations

from pathlib import Path
from typing import Tuple

from pypdf import PdfReader

from .models import Issue


def read_pdf_text(pdf_path: Path) -> tuple[int, str]:
    reader = PdfReader(str(pdf_path))
    pages = len(reader.pages)
    texts = []
    for p in reader.pages:
        try:
            t = p.extract_text() or ""
        except Exception:
            t = ""
        texts.append(t)
    return pages, "\n".join(texts)


def check_pdf_openable(pdf_path: Path) -> list[Issue]:
    try:
        _ = PdfReader(str(pdf_path))
        return []
    except Exception as e:
        return [Issue(severity="ERROR", kind="pdf_open", message=f"Cannot open PDF: {e}")]


def check_basic_content(pdf_path: Path, min_pages: int, min_text_chars: int) -> list[Issue]:
    issues: list[Issue] = []
    try:
        pages, text = read_pdf_text(pdf_path)
    except Exception as e:
        return [Issue(severity="ERROR", kind="pdf_read", message=f"Failed reading PDF text: {e}")]

    if pages < min_pages:
        issues.append(
            Issue(
                severity="MINOR",
                kind="too_few_pages",
                message=f"PDF has only {pages} pages (< {min_pages}).",
            )
        )

    if len(text.strip()) < min_text_chars:
        issues.append(
            Issue(
                severity="MINOR",
                kind="too_little_text",
                message=f"Extracted text is {len(text.strip())} chars (< {min_text_chars}). Could be scanned image or very short.",
            )
        )

    return issues
