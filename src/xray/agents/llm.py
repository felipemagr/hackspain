"""The seam where a language model plugs in, and the client we use behind it."""

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
        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]


def build_llm(settings: Settings) -> LLM | None:
    """The configured model, or None when no key is set so agents fall back to raw output."""
    if not settings.helmcode_api_key:
        return None
    return OpenAICompatibleLLM(
        api_key=settings.helmcode_api_key,
        model=settings.llm_model,
        base_url=settings.helmcode_base_url,
    )
