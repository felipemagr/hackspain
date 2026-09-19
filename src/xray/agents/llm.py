"""The seam where a language model plugs in. No provider is wired yet."""

from typing import Protocol


class LLM(Protocol):
    def complete(self, system: str, user: str) -> str: ...
