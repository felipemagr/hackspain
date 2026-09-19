"""Semantic web search through the Exa REST API: https://exa.ai/docs/reference/search"""

from datetime import date
from typing import Literal

import httpx
from pydantic import BaseModel, Field

SEARCH_URL = "https://api.exa.ai/search"
REQUEST_TIMEOUT_SECONDS = 30.0

Category = Literal["company", "news", "financial report"]


class ExaResult(BaseModel):
    title: str | None = None
    url: str
    published_date: str | None = Field(default=None, alias="publishedDate")
    text: str = ""


def search(
    query: str,
    api_key: str,
    num_results: int = 5,
    category: Category | None = None,
    published_after: date | None = None,
    text_chars: int = 700,
) -> list[ExaResult]:
    """Run one search and return the hits with the first `text_chars` of each page."""
    body: dict = {
        "query": query,
        "numResults": num_results,
        "contents": {"text": {"maxCharacters": text_chars}},
    }
    if category:
        body["category"] = category
    if published_after:
        body["startPublishedDate"] = f"{published_after.isoformat()}T00:00:00.000Z"
    response = httpx.post(
        SEARCH_URL,
        headers={"x-api-key": api_key},
        json=body,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return [ExaResult.model_validate(hit) for hit in response.json()["results"]]
