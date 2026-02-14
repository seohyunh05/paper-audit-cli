from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader


def extract_text(pdf_path: Path, max_chars: int | None = None) -> str:
    reader = PdfReader(str(pdf_path))
    texts: list[str] = []
    total = 0
    for page in reader.pages:
        t = page.extract_text() or ""
        if t:
            texts.append(t)
            total += len(t)
            if max_chars is not None and total >= max_chars:
                break
    out = "\n".join(texts).strip()
    if max_chars is not None:
        return out[:max_chars]
    return out


def count_pages(pdf_path: Path) -> int:
    reader = PdfReader(str(pdf_path))
    return len(reader.pages)
