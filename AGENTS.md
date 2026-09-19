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
make              # list every target
make install      # uv sync + notebook output stripping
make inspect      # print shape and dtypes of every CSV in data/raw
make test-quick   # pytest, stop at first failure
make format       # ruff autofix + format
make ci           # lint, format check and tests: run before pushing
```

Always go through `uv` (`uv run ...`, `uv add ...`), never bare `pip` or `python`.

## 5. Repo layout

```
src/xray/
  config.py, settings.py   paths, constants, runtime settings
  pipeline/                raw CSVs -> parquet -> monthly panel (pandas lives only here)
  scoring/                 score, explain, monitor, offer, submit
  agents/                  research, macro and narrator agents, tools under agents/tools
  integrations/            outbound clients, one module per service
  api/                     FastAPI backend, one router per resource in api/routers
tests/                     mirrors src/xray: tests/pipeline, tests/api, tests/agents
notebooks/                 exploration, outputs stripped on commit
data/raw/                  challenge CSVs, not in git
data/processed/            derived tables, not in git
data/serving/              pipeline output read by the API, not in git
```

Dependencies point one way: `config`/`settings` <- `pipeline` <- `scoring` <- `agents`, `api`. A new
module goes in the package that owns its deliverable (table in `docs/brief.md` section 8), with its
test in the mirror folder under `tests/`.

Other people and agents work in this same checkout at the same time (product and infra). Stage only the files you changed, never `git add -A`, and do not switch branches or rewrite history without asking.

## 6. Before every push: update `docs/brief.md`

`docs/brief.md` is the shared context file. Every agent and teammate reads it first, so it has to
describe the project as it is right now.

Every time you push, check these sections and fix what your work made wrong, in the same push:

| Section | Update it when you changed |
|---|---|
| 7. What we are building | the product, the buyer, the layers or the demo script |
| 8. Mapping deliverables to the repo | which module owns a deliverable, or added a new one |
| 9. Modelling guardrails | a decision about splits, leakage, units or the score's shape |
| 10. Open questions | you answered one, or found a new one |

How to write the edit:

- Facts only. What is true now. Not what changed, not who changed it, not when.
- Edit the line or table row that is already there. Never append a changelog, a "recent updates"
  section or a date stamp. History is the git log's job.
- One line per fact. No adjectives, no hedging, no filler.
- An answered open question gets deleted from section 10 and its answer written into the section
  it affects.
- Nothing in those sections became wrong: push without touching the file. Do not pad it.
