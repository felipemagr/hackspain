"""The seam where a language model plugs in, and the client we use behind it."""

import json
from collections.abc import Iterator
from typing import Protocol

import httpx
from pydantic import BaseModel

from xray.settings import Settings

REQUEST_TIMEOUT_SECONDS = 120.0


class LLM(Protocol):
    def complete(self, system: str, user: str) -> str: ...


class OpenAICompatibleLLM:
    """Chat completions over any OpenAI-compatible endpoint. Helmcode by default."""

    def __init__(
        self, api_key: str, model: str, base_url: str, reasoning_effort: str | None = None
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.reasoning_effort = reasoning_effort

    def stream(self, system: str, user: str) -> Iterator[str]:
        """The answer piece by piece. Always streamed: Helmcode drops a connection that stays
        silent while a reasoning model thinks for more than a minute."""
        body = {
            "model": self.model,
            "temperature": 0.2,
            "stream": True,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        with httpx.stream(
            "POST",
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=body,
            timeout=REQUEST_TIMEOUT_SECONDS,
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if not line.startswith("data:") or line.endswith("[DONE]"):
                    continue
                choices = json.loads(line.removeprefix("data:"))["choices"]
                if choices and (text := choices[0]["delta"].get("content")):
                    yield text

    def complete(self, system: str, user: str) -> str:
        return "".join(self.stream(system, user))


def complete_json[T: BaseModel](llm: LLM, system: str, user: str, schema: type[T]) -> T:
    """Ask for JSON and validate it.

    Models wrap the object in a code fence or prose even when told not to: only the text from
    the first `{` to the last `}` is read.
    """
    text = llm.complete(system, user)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError(f"No JSON object in the answer: {text.strip()[:120]!r}")
    return schema.model_validate_json(text[start : end + 1])


def build_llm(settings: Settings, reasoning_effort: str | None = None) -> LLM | None:
    """The configured model, or None when no key is set so agents fall back to raw output.

    `reasoning_effort="low"` is for the chat: first token in about 3 s instead of 25 s.
    """
    if not settings.helmcode_api_key:
        return None
    return OpenAICompatibleLLM(
        api_key=settings.helmcode_api_key,
        model=settings.llm_model,
        base_url=settings.helmcode_base_url,
        reasoning_effort=reasoning_effort,
    )
