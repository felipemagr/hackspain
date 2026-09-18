# Git Commit Guidelines

## Format

Conventional commits:

```
<type>(<optional scope>): <description>

[optional body]
```

### Types

- `feat`: new feature
- `fix`: bug fix
- `docs`: documentation
- `style`: formatting, no logic change
- `refactor`: code refactoring
- `perf`: performance
- `test`: adding or updating tests
- `chore`: maintenance, dependencies, configs

### Examples

```bash
feat(score): add rolling DSO trend signal
fix(api): return 404 for unknown group
docs: add demo run instructions

feat(monitor): alert on sustained score drops

- Flag drops that persist for two months
- Ignore single-month dips
```

## Rules

1. **Lowercase type**: `feat`, not `FEAT`.
2. **Imperative mood**: "add feature", not "added feature".
3. **Subject line under 72 characters**, no trailing period.
4. **Blank line between subject and body**.
5. **Small, working commits**: with several people on the repo, commit often and pull before pushing.
6. Commit or push only when asked.
