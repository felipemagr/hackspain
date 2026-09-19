# Frontend and Design

The demo is a third of the score, so UI work does not get improvised. It goes through the `impeccable` skill vendored in `.claude/skills/impeccable/` ([impeccable.style](https://impeccable.style/)).

## Which skill owns what

- `impeccable`: every screen, component, layout, copy and polish decision. If another design skill is installed (`frontend-design`, `artifact-design`), impeccable wins for anything inside this repo.
- `dataviz`: every chart (score trajectory, driver breakdown, portfolio views). Load it before writing chart code; impeccable still decides where the chart sits and how the page around it looks.
- `run`: open the demo and look at it before calling UI work done.

## Order of work

1. `/impeccable init` once per repo: writes `PRODUCT.md` (buyer, users, tone) from `docs/brief.md`. Commit it.
2. `/impeccable shape <screen>` before coding a new screen: agree on structure first.
3. Build. Demo screens are **Operate** mode: scanability and consistency over expression.
4. `/impeccable document` once the first screen exists: writes `DESIGN.md` (tokens, type, components). Later screens follow it instead of inventing a new look.
5. `/impeccable critique <screen>` then `/impeccable polish <screen>` before the pitch. `audit` and `harden` only if time allows.

## Rules

- `PRODUCT.md` and `DESIGN.md` live at the repo root and are the source of truth; update them rather than contradicting them in code.
- Do not edit files under `.claude/skills/impeccable/`: it is a vendored copy (v4.1.1). Update it with `npx impeccable update`.
- The six questions in `CLAUDE.md` drive the information hierarchy: each one must be answerable from the screen without reading a manual.
