# Hermes bounded task/session recovery (issue #45)

This contract is injected by the reviewed `HermesAgent` task-start prompt. It is not a new authorization or an automatic retry policy. The private queue, Bridge journal and remote GitHub identities remain the authorities for effects. Keep checkpoints and state in a private persistent volume outside every checkout; back them up consistently to a secured off-host destination. Never commit private state, auth stores, tokens, device codes, raw logs or secret-bearing prompts.

## While running

Before and after tests, commit, push and draft publication, write a bounded private checkpoint atomically (0600 file and directory fsync). Include task/authorization identity, pinned runner/base/branch, run/session/worktree mapping, last **confirmed** stage, intent versus observed head and test/PR/CI receipts, next work and uncertainty. A checkpoint is a self-report, not proof of GitHub publication. The Bridge owns draft creation: the child must **not** POST a PR or claim a draft was published. Keep secrets and raw output out. A final handoff is best effort, never the only checkpoint.

## Graceful budget/context stop

If still able to act, flush the checkpoint and publish only sanitized paused/blocked status through the approved issue path. Preserve the worktree and journals. Do not rush commit/push, weaken checks, or infer a quota reset from an assumed five-hour window. A final message cannot be guaranteed at quota exhaustion.

## Abrupt exit, HTTP 429 or process loss

A dead session cannot write a farewell. The deterministic supervisor retains the claimed run, process exit/stage diagnostics and any publication intent, marks it blocked/uncertain, and prohibits a second dispatch. Honor Retry-After or a trustworthy reset when provided; unknown provider reset stays UNKNOWN. Empty inbox polls never call a model. No unbounded retry loop.

## New session / continuation

First read the canonical issue, this pinned runbook, private checkpoint and Bridge journal, then inspect the actual preserved local Git worktree/branch and remote branch, PR and exact-head CI **read-only**. Distinguish confirmed operation from intent; reconcile uncertain push/POST instead of repeating it. Do not reset, clean, stash, overwrite or delete old runs, invent receipts, or create a second PR. A new conversation may inspect/report under its approved scope; it cannot redispatch a blocked `Bridge.once`. New effectful work needs separately reviewed recovery/enrollment policy and a new bounded authorization/run identity as appropriate. A changed scope, missing checkpoint, contradictory Git state, or uncertain remote effect is BLOCKED with a concrete report. Never retry historic #26/#27/#30/#34/#37 as recovery for this pipeline.

The dormant inbox is one-shot per signed grant and enrolled task. Installation/disable/rollback is documented in `ops/github_inbox/README.md`; no activation is implied by a merged PR.
