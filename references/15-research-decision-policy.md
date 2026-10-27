# 15 — Research and Decision Policy

## Rule

Do not add technical decisions to the skill without research. Even a small decision
needs sources, rationale and test impact.

## Decision log format

Create `decision_log/YYYY-MM-DD-<slug>.md` for every decision:

```markdown
# Decision: <short title>

## Status
proposed | accepted | rejected | superseded

## Context
What problem is being solved?

## Sources checked
- Source name + URL + date
- Prefer official documentation, papers and vendor documentation.

## Decision
What was selected?

## Alternatives
What was rejected?

## Risks
What happens if the decision is wrong?

## Tests added
Which acceptance or unit tests were added?

## Rollback
How can the change be reverted?
```

## Source priority

1. Official exchange / Docker / library documentation.
2. Academic papers or vendor technical blogs.
3. Open-source code and tests.
4. Blogs/opinion only as supporting sources.

## Special rule

Profitability or success-probability claims require this project's own forward paper
test results. External firm profits or academic accuracy do not directly establish
our expected returns.
