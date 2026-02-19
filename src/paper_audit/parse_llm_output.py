from __future__ import annotations

import re
from typing import List

from .models import Issue


def parse_llm_findings(raw: str) -> List[Issue]:
    text = (raw or "").strip()
    if not text:
        return []

    lowered = text.lower()
    if "no significant errors found regarding the main results" in lowered:
        return []

    issues: List[Issue] = []

    # Heuristic split by severity mentions
    pattern = re.compile(r"\b(critical|intermediate|minor)\b", re.IGNORECASE)
    hits = list(pattern.finditer(text))

    if not hits:
        return [Issue(level="INTERMEDIATE", code="LLM_FLAG", message=text[:2000])]

    for idx, m in enumerate(hits[:6]):  # cap
        sev = m.group(1).upper()
        sev = "CRITICAL" if sev.startswith("CRIT") else "INTERMEDIATE" if sev.startswith("INTER") else "MINOR"

        start = m.start()
        end = hits[idx + 1].start() if idx + 1 < len(hits) else len(text)
        chunk = text[start:end].strip()

        issues.append(Issue(level=sev, code=f"LLM_{sev}", message=chunk[:2000]))

    return issues
