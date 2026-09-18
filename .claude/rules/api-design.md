---
paths:
  - "**/api/**"
---

# FastAPI Guidelines

Applies if the demo backend is FastAPI.

## Resource Naming

```bash
# GOOD: plural nouns, hyphens, shallow
GET /api/v1/groups
GET /api/v1/groups/{group_id}
GET /api/v1/groups/{group_id}/scores
GET /api/v1/credit-offers

# BAD
GET /group/{id}              # singular
GET /credit_offers           # underscores
GET /a/{a}/b/{b}/c/{c}/d/{d} # too deep
```

Verbs: `GET` list/read, `POST` create, `PATCH` update, `DELETE` delete. Version in the URL path (`/api/v1`).

## Routes

```python
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/groups", tags=["groups"])


class GroupScoreResponse(BaseModel):
    """Latest score for a group."""

    group_id: str
    score: float
    trend: str | None = None


@router.get("/{group_id}", response_model=GroupScoreResponse)
async def get_group(
    group_id: str,
    service: ScoreService = Depends(get_score_service),
) -> GroupScoreResponse:
    """Get the latest score for a group."""
    result = service.get_latest(group_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group not found",
        )
    return result
```

## Forgiving Request Models

Accept whatever can be processed sensibly. Keep `422` for input that truly cannot be handled.

- Don't add length/size caps that aren't about correctness. Truncate over-long free text in a `mode="before"` validator instead of rejecting it.
- Normalize alternate shapes in a `before` validator instead of rejecting them.
- Prune empty entries so one blank item doesn't fail the whole request.
- Prefer `T | None = None` when a caller may legitimately omit a field.

Leniency applies to shape and size, never to correctness: keep validating enums and types strictly.

## Error Handling

- Use `status.HTTP_*` constants, never hardcoded numbers.
- A global exception handler logs unexpected errors and returns a generic 500. A demo must not show a stack trace.

## Pagination

Offset-based by default:

```python
offset: int = Query(default=0, ge=0),
limit: int = Query(default=20, ge=1, le=100),
```

Response carries `data`, `total`, `offset`, `limit`.

## Dependency Injection & Lifecycle

- Use `Depends()` for services and settings; `@lru_cache` on `get_settings()`.
- Load data/models once in a `lifespan` context manager, not per request.

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.scores = load_scores()
    yield

app = FastAPI(lifespan=lifespan)
```

## Key Conventions

1. Pydantic models for requests and responses, lenient on input shape.
2. `Depends()` for dependency injection.
3. Status constants, never hardcoded codes.
4. Docstrings on endpoints (they show up in OpenAPI, which is useful during the demo).
5. Heavy loading in `lifespan`, not in request handlers.
