from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from .models import Issue


@dataclass(frozen=True)
class LLMConfig:
    model: str
    reasoning_effort: str = "low"


class LLMClient:
    def __init__(self, cfg: LLMConfig):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set in environment.")
        self._client = OpenAI(api_key=api_key)
        self._cfg = cfg

    def audit_text(self, system_prompt: str, paper_title: str, paper_text: str) -> tuple[list[Issue], dict[str, Any]]:
        # Use Responses API style through OpenAI python client
        # We keep it simple: ask for structured JSON-ish output, then parse lightly.
        prompt = (
            f"{system_prompt}\n\n"
            f"### PAPER TITLE\n{paper_title}\n\n"
            f"### PAPER TEXT (EXCERPT)\n{paper_text}\n"
        )

        resp = self._client.responses.create(
            model=self._cfg.model,
            input=prompt,
            reasoning={"effort": self._cfg.reasoning_effort},
        )

        text = ""
        try:
            # SDK returns output as a list of content blocks; this is safest fallback
            for item in resp.output:
                for c in getattr(item, "content", []):
                    if getattr(c, "type", "") == "output_text":
                        text += c.text
        except Exception:
            text = str(resp)

        issues = _heuristic_parse_issues(text)
        raw = {"response_text": text}
        return issues, raw


def _heuristic_parse_issues(text: str) -> list[Issue]:
    """
    Lightweight parser: we try to detect CRITICAL/INTERMEDIATE/MINOR sections.
    If the model says "No significant errors..." we return [] (no issues).
    """
    t = (text or "").strip()
    if not t:
        return [Issue(category="SYSTEM", message="Empty LLM response")]

    if "No significant errors found regarding the main results" in t:
        # optionally keep minor typos, but your policy deletes no-issue threads anyway
        return []

    issues: list[Issue] = []
    # Simple markers
    for cat in ("CRITICAL", "INTERMEDIATE", "MINOR"):
        if cat in t:
            issues.append(Issue(category=cat, message=f"{cat} finding(s) reported. See thread output.", detail=t[:5000]))
            break

    if not issues:
        # Default: treat as intermediate so it is kept for review
        issues.append(Issue(category="INTERMEDIATE", message="LLM returned findings (unclassified). See details.", detail=t[:5000]))

    return issues
