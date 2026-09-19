"""Web search through the Tavily REST API: https://docs.tavily.com/documentation/api-reference/endpoint/search"""

import httpx
from pydantic import BaseModel

SEARCH_URL = "https://api.tavily.com/search"
REQUEST_TIMEOUT_SECONDS = 15.0


class SearchResult(BaseModel):
    title: str
    url: str
    content: str


def search(query: str, api_key: str, max_results: int = 5) -> list[SearchResult]:
    """Run one search and return the hits in Tavily's relevance order."""
    response = httpx.post(
        SEARCH_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={"query": query, "max_results": max_results},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return [SearchResult(**hit) for hit in response.json()["results"]]
