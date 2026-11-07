---
name: signal-desk-autonomous-development
description: Use when reviewing Signal Desk's bounded issue-driven development task, Bridge queue, or recovery handoff.
---

# Signal Desk autonomous-development boundary

This repository skill is project-specific. It is not a copy of a private Hermes profile, global skill, credential store, or runtime queue. It does not authorize an agent, host operation, or task.

- Start with the live #41 coordination thread and the exact open task issue #43; preserve its UTF-8 body digest and the separate private authorization. The #45 inbox is an **optional dormant intake**, not a second executor. Its `enroll` begins disabled; neither a merged PR nor a comment wakes Hermes. See [`ops/github_inbox/README.md`](../../ops/github_inbox/README.md).
- Keep the existing host runner `00acd27132b68264ee2ab1692d3024f09c640c6d` untouched. The candidate new runner is the reviewed #46 merge `e84021a786004456a12de9e25eae50d191da6cf1`; a new independent clone, private interpreter context, and explicit approval are needed before a future task. The operator-package input manifest and limitations are in [`ops/bridge_one_shot/PACKAGE_REVIEW.md`](../../ops/bridge_one_shot/PACKAGE_REVIEW.md).
- One durable queue claim precedes effects. Only `BridgeQueue -> Bridge.once -> HermesAgent` executes a task. The child edits/tests/commits/pushes its frozen artifact; Bridge alone publishes and verifies the draft PR. A local checkpoint is not a remote receipt. Never dispatch an already claimed, blocked, or ambiguous run again.
- At task start inject the pinned [`docs/HERMES_SESSION_RECOVERY.md`](../../docs/HERMES_SESSION_RECOVERY.md), and write private, bounded checkpoints before effects. On interruption, read the queue mapping, Bridge journal, local worktree and exact remote branch/PR/head/CI **before** proposing continuation. Keep private auth, OAuth, session data, state, backups, and host evidence outside Git.
- Manager comments require the separately verified signed grant; shared-account author names and comment text are not authority. The signer must be manager-only and the public verifier worker-only. The current repository's worker credential can change unprotected workflow code; therefore the proposed GitHub Actions comment-signer route is **not approved**. See the evidence and missing protection in the package review.
- The final #41 root handoff must be separately reviewed and bounded to one approved #43 run plus exact-ID cleanup. Successful local tests and a draft PR are not host acceptance. Issue #44's portable build/restore and one-container acceptance remains subsequent work; do not call the current two-service one-shot proposal portable or installed.
