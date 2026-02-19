from __future__ import annotations

from .models import Issue

SEVERITIES = ("CRITICAL", "INTERMEDIATE", "MINOR")


def parse_llm_findings(raw: str) -> list[Issue]:
    """
    Lightweight parser:
    - If the model says no significant errors, treat as no issues.
    - Otherwise, create one Issue per severity section we can detect.
    """
    text = (raw or "").strip()
    if not text:
        return []

    lowered = text.lower()
    if "no significant errors found regarding the main results" in lowered:
        return []

    issues: list[Issue] = []

    # If model clearly indicates critical/intermediate/minor
    for sev in SEVERITIES:
        if sev.lower() in lowered:
            issues.append(Issue(severity=sev, kind="llm", message=text))

            # If critical or intermediate exists, that's enough; return early to avoid duplicates
            if sev in ("CRITICAL", "INTERMEDIATE"):
                return issues

    # fallback: unknown but non-empty response => record as MINOR (review needed)
    issues.append(Issue(severity="MINOR", kind="llm", message=text))
    return issues
