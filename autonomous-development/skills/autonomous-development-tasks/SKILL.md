---
name: autonomous-development-tasks
description: "Use when asked to queue a development task by chat."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [development, tasks, queue, orchestration]
    related_skills: [hermes-agent]
---

# Autonomous development tasks

## When to Use

Use when the user wants to queue a natural-language development task, a related follow-up, or check the external supervisor's task status. Do not trigger when they instead ask you to perform coding directly in this conversation.

This installation's workflow is `/opt/data/autonomous-development/orchestrator.py`; read `/opt/data/autonomous-development/README.md` if you need operational details. Distinguish queue submission from execution.

- When the user explicitly asks to **queue or submit** a development task, resolve its Git repository from their explicit path or the clearly active project; ask only if ambiguous. Preserve the user's request without inventing acceptance criteria. Keep it short (≤2,000 characters) and do not include secrets. Never paste credentials or full transcripts into task briefs or checkpoints.
- Submit via a local tool using an argument vector, not shell concatenation, to invoke `python3 /opt/data/autonomous-development/orchestrator.py submit --repo REPO --text-file -` with the natural-language request on stdin. Report the returned task ID and `queued` status, not that the agent has started. No manual brief creation is needed.
- For an explicitly related subtask, add `--related PARENT_TASK_ID`: the external supervisor resumes the completed parent's exact session. Never infer relatedness when the user says a task is independent. For an independent task, omit `--related`; the supervisor omits `--resume`/`--continue`. Add `--checkpoint EXACT_PATH` only when one relevant, existing project checkpoint is explicitly selected or genuinely justified by task context; do not attach all prior handoffs.
- To report progress, run `python3 /opt/data/autonomous-development/orchestrator.py status` (read-only). To acknowledge a quota pause, require the user's explicit request and confirmed reset; `ack-quota --task ID` never retries the blocked task.
- **Never launch `orchestrator.py run`, `hermes chat`, or another Hermes agent from this active conversation**. A NO-GO two-service draft is staged in `/opt/data/autonomous-development/compose.supervisor.yml` but NOT activated; see `SERVICE_DEPLOYMENT_PLAN.md`. Its networkless observer cannot execute tasks; the worker is staged on a dedicated internal/isolated bridge with a credential-free exact-host Codex CONNECT proxy, but the subnet, host firewall persistence, and negative network tests remain unverified on the Docker host. The worker has no auth bind or credentials until separately approved provisioning. Do not start it before the host gates and explicit approval (a Compose profile is not an approval gate; explicitly targeted services can start). Do not start the worker or a manual watcher from this conversation. Never run both a manual watcher and the approved worker. Do not claim it is running without checking process status, and do not restart production services.
- A queued task is not a completed task. Completion requires a successful external run, observed Git changes, independent test-phase verification, and checkpoint readback. On missing recipe, quota, or failure, the watcher remains alive but the queue pauses durably without retrying; report the block and required manual `ack-block` or post-reset `ack-quota`. On SIGTERM during a turn, the synthetic worker is terminated and the task stays `running` for manual review.
