"""The seam where a language model plugs in, and the client we use behind it."""

import json
from typing import Protocol

import httpx

from xray.settings import Settings

REQUEST_TIMEOUT_SECONDS = 120.0


class LLM(Protocol):
    def complete(self, system: str, user: str) -> str: ...


class OpenAICompatibleLLM:
    """Chat completions over any OpenAI-compatible endpoint. Helmcode by default."""

    def __init__(self, api_key: str, model: str, base_url: str):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")

    def complete(self, system: str, user: str) -> str:
        """The full answer, read as a stream: Helmcode drops a connection that stays silent
        while a reasoning model thinks for more than a minute."""
        parts = []
        with httpx.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "temperature": 0.2,
                "stream": True,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data:") or line.endswith("[DONE]"):
                    continue
                choices = json.loads(line.removeprefix("data:"))["choices"]
                if choices and (text := choices[0]["delta"].get("content")):
                    parts.append(text)
        return "".join(parts)


def build_llm(settings: Settings) -> LLM | None:
    """The configured model, or None when no key is set so agents fall back to raw output."""
    if not settings.helmcode_api_key:
        return None
    return OpenAICompatibleLLM(
        api_key=settings.helmcode_api_key,
        model=settings.llm_model,
        base_url=settings.helmcode_base_url,
    )
