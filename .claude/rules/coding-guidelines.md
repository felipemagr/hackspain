# Coding Guidelines

Behavioral guidelines to reduce common LLM coding mistakes.

**Tradeoff:** this is a hackathon. Bias toward shipping something that works and demos well. For trivial tasks, use judgment.

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them, don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code. Three similar lines are better than a premature helper.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios. Trust internal code and framework guarantees.
- Don't add architecture layers unless the complexity warrants it. A script or a flat module is fine.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Don't add docstrings, type annotations, or comments to code you didn't change.
- Match existing style, even if you'd do it differently. Let the formatter handle formatting.
- If you notice unrelated dead code, mention it, don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: every changed line should trace directly to the user's request.

## 4. Docstrings & Comments: Lean by Default

**Less prose, more signal. Args/Returns stay; narrative goes.**

Keep:
- One-line summary on every public function/class.
- `Args:` / `Returns:` / `Raises:` sections when they aid the caller.
- Invariants not derivable from the code (e.g. "input must be sorted by month").
- Counter-intuitive design choices explained briefly.

Trim aggressively:
- Narrative of "why this commit changed it": that's the commit message, not the file.
- Restating what the code already says.
- War-story comments referencing past bugs: keep the invariant, drop the story.
- Multi-paragraph docstrings on internal one-use functions.
- Step-by-step narration of obvious control flow.

Ask yourself: "If I delete this comment, would a reader of the code be confused?" If no, delete it.

**No em dashes in code, docstrings, or comments.** Use a colon, a comma, or a line break. (Prompts and other LLM-facing string data are exempt: those are content, not code.)

**Avoid emoji in code, docstrings, and comments** unless explicitly asked (UI strings and demo copy are fine).

## 5. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add a feature/signal" -> "Measure the validation metric before and after"
- "Fix the bug" -> "Reproduce it, then make the reproduction pass"
- "Refactor X" -> "Same outputs before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] -> verify: [check]
2. [Step] -> verify: [check]
```

Before calling something done: run it, run the tests that exist, and run the linter/formatter.

## 6. Data & Secrets

- Never commit secrets, API keys or `.env` files.
- The challenge dataset is synthetic, but check size before committing data files; ask before adding anything large to git.
- Strip notebook outputs before committing notebooks.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.
