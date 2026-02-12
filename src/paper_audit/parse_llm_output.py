from __future__ import annotations
import re
from typing import List, Tuple
from .models import Issue

NO_SIG_RE = re.compile(r"No significant errors found regarding the main results\.", re.IGNORECASE)
CRIT_RE = re.compile(r"\bCRITICAL ERROR\b", re.IGNORECASE)
INT_RE  = re.compile(r"\bINTERMEDIATE ERROR\b", re.IGNORECASE)
MIN_RE  = re.compile(r"\bMINOR ERROR\b", re.IGNORECASE)

def _split_sections(text: str) -> List[Tuple[str, str]]:
    markers = [("CRITICAL", CRIT_RE), ("INTERMEDIATE", INT_RE), ("MINOR", MIN_RE)]
    hits = []
    for cat, rx in markers:
        for m in rx.finditer(text):
            hits.append((m.start(), cat))
    hits.sort(key=lambda x: x[0])

    if not hits:
        return []

    sections = []
    for i, (pos, cat) in enumerate(hits):
        end = hits[i + 1][0] if i + 1 < len(hits) else len(text)
        sec = text[pos:end].strip()
        sections.append((cat, sec))
    return sections

def issues_from_llm_output(output: str) -> List[Issue]:
    if not output:
        return []
    if NO_SIG_RE.search(output):
        return []

    sections = _split_sections(output)
    if not sections:
        # If it didn't label, keep as an intermediate warning (so thread isn't auto-deleted silently).
        return [Issue(
            code="LLM_UNLABELED_FINDING",
            message=output.strip()[:4000],
            severity="warning",
            category="INTERMEDIATE",
            meta={"note": "No explicit taxonomy headers found in output."}
        )]

    issues: List[Issue] = []
    for cat, sec in sections:
        sev = "error" if cat in ("CRITICAL", "INTERMEDIATE") else "warning"
        issues.append(Issue(
            code=f"LLM_{cat}_FINDING",
            message=sec[:4000],
            severity=sev,
            category=cat,
            meta={}
        ))
    return issues
