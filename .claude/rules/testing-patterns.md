---
paths:
  - "tests/**"
---

# Testing Guidelines

Hackathon scope: test what would silently break the score or the demo, not everything.

## What to Test

- Feature/signal computation on small hand-built frames where the right answer is obvious.
- Edge cases in the data: groups with one company, months with no transactions, unpaid invoices, missing dates.
- The scoring entry point end to end on a tiny fixture: output has one score per group per month, within the expected range.
- API endpoints the demo depends on (happy path plus not-found).

## What to Mock

**Mock only** external services (LLM APIs, HTTP calls).

**Do not mock** your own services, feature functions or data structures: test them directly with fixtures.

When patching with `pytest-mock`, call `mock.reset_mock()` before setting up return values.

## Fixtures

```python
@pytest.fixture
def sample_invoices() -> pd.DataFrame:
    """Two issued invoices: one paid late, one still open."""
    return pd.DataFrame(
        {
            "company_id": ["c1", "c1"],
            "issue_date": pd.to_datetime(["2025-01-05", "2025-02-05"]),
            "due_date": pd.to_datetime(["2025-02-04", "2025-03-07"]),
            "paid_date": pd.to_datetime(["2025-03-01", None]),
            "amount": [1000.0, 500.0],
        }
    )
```

Use invented data with obviously fake names (`Example Corp`). Put shared fixtures in `conftest.py`.

## Structure

```python
class TestHealthScore:
    def test_score_is_bounded(self, sample_group):
        result = score_group(sample_group)
        assert 0 <= result.score <= 100

    def test_handles_group_without_debt(self, group_without_debt):
        assert score_group(group_without_debt) is not None
```

Use `@pytest.mark.parametrize` for input/expected tables.

## Key Rules

1. **Keep tests lean**: meaningful behavior and edge cases only. No trivial tests for obvious one-liners.
2. **Mock only external services**, never your own code.
3. **Use fixtures for test data**.
4. **One behavior per test**, group related tests in classes.
5. **Multiple assertions are OK** when verifying the same logical behavior.
6. **Test error cases** with `pytest.raises`.
7. **Descriptive names**: `test_<feature>_<case>`.
8. Async tests need `@pytest.mark.asyncio`.
