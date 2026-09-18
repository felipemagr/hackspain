# AGENTS.md

Instructions for Codex and any other coding agent working in this repo. Claude Code reads `CLAUDE.md` and `.claude/rules/` on its own; other agents do not, so this file explains the scheme and asks you to follow it by hand.

## 1. Read the project context first

Read [`CLAUDE.md`](CLAUDE.md) before doing anything. It holds the challenge brief, the six questions the system must answer, the deliverables, the dataset description and the modelling guardrails (group-level splits, no leakage from the future, explainable scores). It is the single source of truth for project context; this file does not duplicate it.

## 2. How the rules are organised

Rules live in `.claude/rules/`, one markdown file per topic. There are two kinds:

- **Always-on rules**: no frontmatter. They apply to every task.
- **Path-scoped rules**: they start with a YAML frontmatter block listing `paths:` globs. They apply only when you read or edit a file matching one of those globs.

```markdown
---
paths:
  - "tests/**"
---
```

Claude Code applies that scoping automatically. You must do it yourself: **before editing a file, open every rule whose scope matches it, plus the always-on ones.**

| Rule file | Scope | What it covers |
|-----------|-------|----------------|
| `.claude/rules/coding-guidelines.md` | always | Think before coding, simplicity first, surgical changes, lean comments, verify before done, no secrets or large data in git |
| `.claude/rules/git-commits.md` | always | Conventional commit format |
| `.claude/rules/python-style.md` | `**/*.py` | Imports, typing, error handling, logging, docstrings, `uv` |
| `.claude/rules/testing-patterns.md` | `tests/**` | What to test, what to mock, fixtures, naming |
| `.claude/rules/api-design.md` | `**/api/**` | FastAPI conventions for the demo backend |

Example: editing `tests/test_data.py` means following `coding-guidelines.md`, `git-commits.md`, `python-style.md` and `testing-patterns.md`.

If a rule conflicts with an explicit user request, the user wins. If two rules conflict, the more specific (path-scoped) one wins.

## 3. Changing the rules

- Rules are shared by every agent and every teammate. Do not edit them as a side effect of another task; change them only when asked.
- New rule: add a file in `.claude/rules/`, add `paths:` frontmatter if it is not universal, and add a row to the table above and to the list at the bottom of `CLAUDE.md`.
- Project context changes go in `CLAUDE.md`, not here.

## 4. Commands

```bash
make install   # uv sync + notebook output stripping
make inspect   # print shape and dtypes of every CSV in data/raw
make test      # pytest
make quality   # ruff check + format check
make format    # ruff autofix + format
```

Always go through `uv` (`uv run ...`, `uv add ...`), never bare `pip` or `python`.

## 5. Repo layout

```
src/xray/        score engine package (config, data loading, then features and scoring)
tests/           pytest suite
notebooks/       exploration, outputs stripped on commit
data/raw/        challenge CSVs, not in git
data/processed/  derived tables, not in git
```

Other people and agents work in this same checkout at the same time (product and infra). Stage only the files you changed, never `git add -A`, and do not switch branches or rewrite history without asking.
