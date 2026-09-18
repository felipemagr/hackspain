---
paths:
  - "**/*.py"
---

# Python Conventions

## Imports

Follow Ruff/isort ordering, groups separated by blank lines:

```python
# 1. Standard library
import logging
from pathlib import Path

# 2. Third-party (alphabetical)
import pandas as pd
from pydantic import BaseModel, Field

# 3. Local (absolute paths)
from xray.features.cashflow import monthly_net_flow
```

- Use **absolute imports**, avoid `../../x`.
- Import specific functions/classes when possible.

## Type Annotations

Modern Python 3.10+ syntax:

```python
api_key: str | None = None
scores_by_group: dict[str, list[float]]
```

Use `Annotated[...]` with `Field(...)` for metadata and `ClassVar` for class-level constants.

## Error Handling

```python
# Specific exceptions, always chained
try:
    result = load_transactions(path)
except FileNotFoundError as e:
    logger.error("Could not load transactions: %s", e)
    raise DataLoadError("Failed to load transactions") from e
```

- Catch specific exceptions, not bare `Exception`, unless returning a documented safe fallback.
- Use `from e` to preserve context.

## Control Flow

- Prefer early returns over nested `if` blocks.
- Instantiate variables close to where they are used.

```python
# GOOD
if df.empty:
    return None
# main logic, no nesting
```

## Pydantic Models

Order: class variables, required fields, optional fields with defaults.

```python
class ScoreResponse(BaseModel):
    """Score for one group at one month."""

    group_id: str
    month: str
    score: float
    drivers: list[str] = Field(default_factory=list)
```

Use `model_dump(mode="json")` when the output must be JSON-compatible (UUIDs, enums, dates).

## Async

Use `async def` only for real I/O (HTTP, DB). Pandas/numpy work is CPU-bound: keep it sync. Use context managers for resources.

## Logging

```python
logger = logging.getLogger(__name__)

# %s formatting, not f-strings
logger.info("Scored %s groups for month %s", n_groups, month)
```

## Docstrings

Google style, lean (see `coding-guidelines.md` section 4):

```python
def rolling_dso(invoices: pd.DataFrame, window: int = 3) -> pd.Series:
    """Compute rolling days sales outstanding per month.

    Args:
        invoices: Issued invoices with issue and payment dates.
        window: Rolling window in months.

    Returns:
        Series indexed by month.
    """
```

## Constants

```python
# Module-level, UPPER_CASE, units in the name
DEFAULT_WINDOW_MONTHS = 3
REQUEST_TIMEOUT_SECONDS = 10.0
```

## Utility Functions

- Single responsibility, prefer pure functions without side effects.
- Comprehensive type hints.
- `@lru_cache` for expensive, repeatable loads (e.g. reading a CSV once).
- Log with context when falling back to a default.

## Package Management

- Dependencies managed with `uv`. Don't use `pip` or `poetry` directly.
- Run scripts with `uv run script.py`, sync with `uv sync`.
