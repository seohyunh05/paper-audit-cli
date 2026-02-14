from __future__ import annotations

from pathlib import Path

from .models import Issue
from .text_extract import extract_text, count_pages


def check_pdf_openable(pdf_path: Path) -> list[Issue]:
    try:
        _ = count_pages(pdf_path)
        return []
    except Exception as e:
        return [Issue(category="SYSTEM", message="PDF cannot be opened", detail=str(e))]


def check_basic_content(pdf_path: Path, min_pages: int, min_text_chars: int) -> list[Issue]:
    issues: list[Issue] = []
    try:
        pages = count_pages(pdf_path)
        if pages < min_pages:
            issues.append(Issue(category="MINOR", message=f"Too few pages: {pages} < {min_pages}"))
    except Exception as e:
        issues.append(Issue(category="SYSTEM", message="Failed to count pages", detail=str(e)))
        return issues

    try:
        text = extract_text(pdf_path, max_chars=max(min_text_chars, 2000))
        if len(text) < min_text_chars:
            issues.append(
                Issue(
                    category="INTERMEDIATE",
                    message=f"Very little extractable text ({len(text)} chars). Possibly scanned/OCR needed.",
                )
            )
    except Exception as e:
        issues.append(Issue(category="SYSTEM", message="Failed text extraction", detail=str(e)))

    return issues
