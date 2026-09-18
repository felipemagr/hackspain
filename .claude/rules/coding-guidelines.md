# Coding Guidelines

How we want agents and teammates to write code in this repo. It is a hackathon: the goal is a working score and a demo that opens, so use judgment on small tasks.

## 1. Understand before you type

- Say which assumptions you are making. When one of them is shaky, ask.
- When a request can be read two ways, show both readings and let the user choose.
- When there is a cheaper way to reach the same result, propose it, even if it contradicts the request.
- When you are confused, stop and say exactly what is confusing.

## 2. Build the smallest thing that works

- Implement what was requested and nothing else.
- A helper earns its place on the second or third use, not the first. Repeating a few lines is fine.
- Skip options, flags and extension points nobody asked for.
- Skip defensive code for cases that cannot happen. Internal code and the framework can be trusted.
- A flat module or a script is a valid design. Add layers only when the problem forces you to.
- When a solution feels long, look for the version that is a quarter of the size.

Check: would an experienced engineer call this overbuilt? Then cut it down.

## 3. Keep diffs narrow

In existing code:
- Leave neighbouring code, comments and formatting alone.
- Working code does not get refactored on the way past.
- Code you did not change does not get new docstrings, types or comments.
- Follow the style that is already there. Formatting is the formatter's job.
- Unrelated dead code gets reported, not removed.

After your own change:
- Delete the imports, variables and functions that your change left unused.
- Older leftovers stay unless the user asks.

Check: can each changed line be justified by the request?

## 4. Comments and docstrings

Write down only what the code cannot say by itself.

Worth writing:
- A one-line summary on public functions and classes.
- `Args:`, `Returns:`, `Raises:` when the caller benefits.
- Preconditions and invariants that are invisible in the code, such as "rows must be sorted by month".
- A short reason for a choice that looks wrong at first sight.

Not worth writing:
- The history of the change. That goes in the commit message.
- A paraphrase of the signature or of the next line.
- The story of a past bug. State the invariant and move on.
- Long docstrings on small internal functions.
- A running commentary on plain control flow.

Check: if the comment vanished, would the next reader be lost? If not, remove it.

Style: no em dashes in code, comments or docstrings; use a colon, a comma or a new line. No emoji there either, unless asked. Text that is content rather than code (prompts, UI copy, demo strings) is exempt.

## 5. Decide how you will know it works

Turn the task into something checkable before starting:
- New feature or signal: compare the validation metric before and after.
- Bug: reproduce it first, then make the reproduction pass.
- Refactor: outputs are identical before and after.

For work with several steps, write the plan as steps with a check each:
```
1. [step] -> check: [how]
2. [step] -> check: [how]
```

Before saying "done": run the code, then `make ci`.

## 6. Data and secrets

- Secrets, API keys and `.env` files never go into git.
- The challenge dataset is synthetic, but it stays out of git anyway (`data/` is ignored). Ask before committing any large file.
- Notebooks are committed without outputs (`make install` sets up the stripper).
