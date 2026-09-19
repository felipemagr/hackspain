"""Web search through the Tavily REST API: https://docs.tavily.com/documentation/api-reference/endpoint/search"""

from typing import Literal

import httpx
from pydantic import BaseModel

SEARCH_URL = "https://api.tavily.com/search"
REQUEST_TIMEOUT_SECONDS = 30.0

Topic = Literal["general", "news", "finance"]
Depth = Literal["basic", "advanced"]


class SearchResult(BaseModel):
    title: str
    url: str
    content: str
    score: float = 0.0
    published_date: str | None = None


class SearchResponse(BaseModel):
    """Hits in Tavily's relevance order, plus its own one-paragraph answer when asked for."""

    answer: str | None = None
    results: list[SearchResult]


def search(
    query: str,
    api_key: str,
    max_results: int = 5,
    topic: Topic = "general",
    search_depth: Depth = "basic",
    include_answer: bool = False,
) -> SearchResponse:
    """Run one search. `advanced` costs two credits instead of one and returns better snippets.

    `topic="news"` is the only one that fills `published_date`.
    """
    response = httpx.post(
        SEARCH_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "query": query,
            "max_results": max_results,
            "topic": topic,
            "search_depth": search_depth,
            "include_answer": include_answer,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return SearchResponse.model_validate(response.json())
