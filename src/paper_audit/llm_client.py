from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import os

from openai import OpenAI

@dataclass
class LLMConfig:
    model: str = "gpt-5"
    reasoning_effort: str = "low"  # low|medium|high (model-dependent)
    api_key_env: str = "OPENAI_API_KEY"

class LLMClient:
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        self._client: Optional[OpenAI] = None

    def available(self) -> bool:
        key = os.getenv(self.cfg.api_key_env)
        return bool(key and key.strip())

    def _get_client(self) -> OpenAI:
        if self._client is None:
            # OpenAI() reads OPENAI_API_KEY from environment by default.
            self._client = OpenAI()
        return self._client

    def review(self, system_prompt: str, user_content: str) -> str:
        """
        Uses the Responses API via the official OpenAI Python SDK:
          client.responses.create(model=..., input=[...])
        """
        if not self.available():
            raise RuntimeError(f"Missing API key env var: {self.cfg.api_key_env}")

        client = self._get_client()

        resp = client.responses.create(
            model=self.cfg.model,
            # Some models support reasoning controls. If unsupported, API may ignore it.
            reasoning={"effort": self.cfg.reasoning_effort},
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        )
        # SDK exposes concatenated output text as output_text per docs/examples.
        return getattr(resp, "output_text", "") or ""
