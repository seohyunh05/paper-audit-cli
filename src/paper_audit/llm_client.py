from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from openai import OpenAI


@dataclass
class LLMConfig:
    model: str = "gpt-4.1-mini"   # choose whatever you want as default


class LLMClient:
    """
    Thin wrapper around OpenAI Responses API.

    IMPORTANT:
    - Keep interface stable: .review(text=..., title=...) is what checks.py calls.
    - Do NOT pass unsupported params like reasoning.effort unless you know the model supports it.
    """
    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config or LLMConfig()
        self.client = OpenAI()

    def review(
        self,
        text: Optional[str] = None,
        title: Optional[str] = None,
        *,
        # allow alternative kwarg name (if some code uses `content=...`)
        content: Optional[str] = None,
        system_prompt: Optional[str] = None,
        max_output_tokens: int = 1200,
    ) -> Dict[str, Any]:
        """
        Returns a dict with at least:
          - "output_text": model's textual response
          - "raw": raw OpenAI response (as dict-like)
        """
        if text is None and content is None:
            raise ValueError("LLMClient.review requires `text` or `content`.")
        body = text if text is not None else content

        # Minimal system prompt fallback; your prompts.py probably overrides this upstream,
        # but we allow direct use too.
        if system_prompt is None:
            system_prompt = (
                "You are a strict technical reviewer. Do not summarize. Only report errors."
            )

        user_msg = body if title is None else f"TITLE: {title}\n\n{body}"

        resp = self.client.responses.create(
            model=self.config.model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_msg},
            ],
            max_output_tokens=max_output_tokens,
        )

        # New SDK: resp.output_text is convenient
        out_text = getattr(resp, "output_text", None)
        if out_text is None:
            # fallback: stringify
            out_text = str(resp)

        return {"output_text": out_text, "raw": resp}
