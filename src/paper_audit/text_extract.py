from __future__ import annotations
from pathlib import Path
from typing import List
from pypdf import PdfReader

def extract_text(pdf_path: Path, max_chars: int) -> str:
    reader = PdfReader(str(pdf_path))
    if reader.is_encrypted:
        return ""

    chunks: List[str] = []
    total = 0

    for page in reader.pages:
        try:
            t = page.extract_text() or ""
        except Exception:
            t = ""
        t = t.strip()
        if not t:
            continue

        remaining = max_chars - total
        if remaining <= 0:
            break

        if len(t) > remaining:
            t = t[:remaining]

        chunks.append(t)
        total += len(t) + 1

        if total >= max_chars:
            break

    return "\n".join(chunks)

def chunk_text(text: str, chunk_chars: int, overlap: int) -> List[str]:
    text = text.strip()
    if not text:
        return []

    if chunk_chars <= 0:
        return [text]

    overlap = max(0, min(overlap, max(0, chunk_chars - 1)))
    out: List[str] = []
    start = 0
    n = len(text)

    while start < n:
        end = min(n, start + chunk_chars)
        out.append(text[start:end])
        if end == n:
            break
        start = max(0, end - overlap)

    return out
