# Task-based Hermes sessions (v0.22.5)

**Persistent service draft (NO-GO; not activated):** See [SERVICE_DEPLOYMENT_PLAN.md](SERVICE_DEPLOYMENT_PLAN.md) and [compose.supervisor.yml](compose.supervisor.yml). The credential-free observer remains networkless and read-only. The worker has only a dedicated internal/isolated bridge; a credential-free CONNECT proxy is the sole proposed outbound path, restricted to exact installed Codex OAuth/inference hosts. The subnet must pass a host route/Docker-network overlap gate before creation, and scoped host firewall persistence plus provider-free positive/negative tests are mandatory before approval. No service/network/firewall was started or changed on the host. The worker has no auth bind or credentials: its private home at `/opt/data/autodev-worker-home` is locally mode 0700; actual host persistence and separate login are unverified. The worker still owns the queue lock, durable 429 pause, and manual acknowledgment behavior. Do not start a manual watcher alongside an approved worker.

## Natural-language task queue (supervised, opt-in)

In this Hermes conversation, say **“Queue a development task for /absolute/repo: …”** with the task in ordinary language. The `autonomous-development-tasks` skill tells the assistant to submit it; you do **not** write a brief or run `task_session.py`. Say **“Queue a related subtask to TASK_ID: …”** to reuse that task's Hermes session, or **“Queue an independent task for /absolute/repo: …; use checkpoint /absolute/path.md”** to select exactly one prior handoff. If the repository is unclear, the assistant must ask. Submission writes a ≤2,000-character, private brief and queue record under `/opt/data/autonomous-development/tasks/`; it does not start an agent. Common credential patterns are refused, but never submit a secret in the first place. `status` lists IDs and states without printing requests.

**One-time external operator step:** in a *separate container terminal*, not a tool invocation from inside this running Hermes conversation, start the supervisor:

```sh
python3 /opt/data/autonomous-development/orchestrator.py run --watch
```

It watches for queued tasks, serializes runs with a lock, and launches a separate `hermes chat --oneshot --query-file … --format stream-json` process. It does **not** change this conversation, switch its TUI, start a gateway service, or install a daemon. Keep that separate terminal/supervisor running; if it stops, new submissions stay queued. For only the current queue, `python3 /opt/data/autonomous-development/orchestrator.py run` drains up to 20 tasks and exits. **We did not start the supervisor or make a Codex request while installing/testing this workflow.** No service restart is required. Each independent queue entry omits `--resume`/`--continue`; a `--related TASK_ID` continuation resumes only its completed parent session. These invocations use the current provider/model and normal Hermes global memory/skills/repo rules; they cannot guarantee zero other context or a fixed subscription saving. No paid provider or fallback is added.

For non-chat use (for example, an external script), submission is also available directly without manually making a brief:

```sh
python3 /opt/data/autonomous-development/orchestrator.py submit \
  --repo /absolute/path/to/repo --text-file -
# Type a short task request on stdin and finish with Ctrl-D; or pipe from a trusted source.
python3 /opt/data/autonomous-development/orchestrator.py status
```

The supervisor gives each turn an 80-iteration cap and a 3,600-second run budget (plus a process timeout); it never retries a failed task. It expects a short structured completion response, confirms observable Git changes without cleaning/stashing/committing, runs `git diff --check`, discovers a test recipe with `hermes verify --detect-only`, and executes **only its test phase** (`--phase test --skip-start`). An absent recipe or zero test commands blocks completion. Review your repository's verification recipe before enabling unattended processing: test scripts are executable code and can have side effects. Do not run a separate manual coding agent against the same working tree concurrently; the queue lock protects supervisors, not other editors. The supervised prompt forbids deployment and production restarts, but it is guidance, not a sandbox or an enforceable command policy. On a pass it invokes the existing `checkpoint.py`, reads back the checkpoint (branch, HEAD, test commands/results, decisions, remaining work), marks the task completed, and starts the next queued task in a new session. The checkpoint is a handoff, not a commit; uncommitted work stays in place. A selected checkpoint is only a **path** in the seed; the agent must actually read it. Parent/child related tasks intentionally share a transcript; independent tasks do not request the parent's transcript.

A failed turn, missing test recipe, failed tests, incomplete report, or absent checkpoint marks the task `blocked` and pauses the queue; `--watch` stays alive but makes no further provider calls until manual review and `ack-block --task BLOCKED_TASK_ID`. A crash or SIGTERM during an in-flight task leaves `running` and prevents new runs until manual inspection; there is **no automatic replay**. A detected quota/HTTP 429 also pauses all later tasks, including across supervisor restarts. Only after confirming the subscription window has reset, explicitly acknowledge that pause (the failed task remains blocked and is never retried automatically):

```sh
python3 /opt/data/autonomous-development/orchestrator.py status
python3 /opt/data/autonomous-development/orchestrator.py ack-quota --task BLOCKED_TASK_ID
```

Inspect blocked/running tasks and the repository manually; to continue an incomplete task, submit a **new** related request only when its parent has completed, or use the earlier `task_session.py resume` workflow. No command here bypasses provider quota. Fresh-session creation, queue transitions, and selective prompt paths were verified with offline fakes and isolated Hermes session storage; a live model-backed end-to-end run remains **unverified**. The real first-turn file read and true context/usage savings are not guaranteed by the supervisor.

## Start a task (manual interactive alternative)

Native Hermes supports fresh CLI/TUI launches and `/new`; it does **not** automatically create a conversation for each Git task. `--continue <name> --create-if-missing` resumes an existing named conversation and is **not** a reliable fresh-task boundary. This lightweight launcher always starts without `--resume`/`--continue`, pins the project directory with `--in`, and seeds a first prompt with only the chosen task-brief path and, optionally, one checkpoint path. It uses Hermes' native session machinery; it neither creates a session row itself nor restarts any service.

1. Put a short task brief in a file (for example `/opt/data/task-briefs/fix-parser.md`); include acceptance criteria, not a transcript or credentials. The file can also be in the repository. The launcher sends **the path**, not the file contents, in its first prompt. Project context from the selected repo (`.hermes.md` ancestor rules or a cwd `AGENTS.md`) and the bounded global memories/skills still follow Hermes' normal loading rules.
2. From an interactive terminal, launch a fresh conversation:

   ```sh
   python3 /opt/data/autonomous-development/task_session.py start \
     --repo /absolute/path/to/repo --task fix-parser \
     --brief /opt/data/task-briefs/fix-parser.md
   ```

   To carry forward one relevant handoff, add `--checkpoint /opt/data/development-checkpoints/<repo-hash>/prior-task.md`. The launcher rejects a handoff from another repository. An unrelated task omits `--checkpoint`. Use `--interface cli` for the classic CLI instead of the default TUI. `--dry-run` validates inputs and prints arguments without launching Hermes. A real launch requires a TTY; it refuses to convert the seeded first prompt into an unattended one-shot API call.
3. Keep related subtasks in the same conversation. For a different task, launch `start` again or use Hermes `/new` manually. Do not use `--continue` for unrelated tasks. `--worktree` is deliberately not set: a fresh session does not imply discarding or relocating existing uncommitted work. For concurrent agents, deliberately choose separate worktrees/repositories yourself.

## Complete and resume

Run real tests, then write a compact handoff **outside** the repository:

```sh
python3 /opt/data/autonomous-development/checkpoint.py \
  --repo /absolute/path/to/repo --task fix-parser \
  --session SESSION_ID \
  --tests 'pytest -q: 21 passed' \
  --decisions 'Parser rejects ambiguous input; retained old API' \
  --remaining 'none'
```

The script reads Git root, branch, HEAD, and dirty-tree status without modifying Git. A dirty worktree means HEAD does **not** contain all work; note outstanding files/changes in `--remaining`. The handoff is a private (0600), at-most-8000-character file at `/opt/data/development-checkpoints/<repo-name>-<path-hash>/<task>.md`; an existing task file is never overwritten. Common API-key/OAuth-token forms are rejected, but no detector proves arbitrary free text safe: **never put credentials, tokens, or full transcripts in a brief or checkpoint**. Use a distinct task slug for a later handoff. For multiple repos, write one handoff per repo. A handoff is not a Git commit or Hermes' opt-in filesystem `/rollback` checkpoint.

To return to the **same** unfinished conversation, use the exact Hermes session ID (from `/status`, the exit summary, or `hermes sessions list --workspace REPO`):

```sh
python3 /opt/data/autonomous-development/task_session.py resume \
  --repo /absolute/path/to/repo --session SESSION_ID
```

Resume does not seed another prompt. It does not delete old sessions. New independent sessions get only their own transcript, the selected brief/checkpoint paths, normal repo rules, global memories, and the skills index. The agent must actually read the named brief/checkpoint on its first turn. Do not preload every prior checkpoint or transcript; retrieve a specific earlier decision with `session_search` when needed. Global `/opt/data/memories/MEMORY.md` and `USER.md` are intentionally not used as task logs; skills under `/opt/data/skills` are for reusable procedures, not per-task state.

Hermes compression is already enabled and in-place; it does not make a fresh independent task session. `gateway.telemetry.session_segments` rotates only Relay instrumentation scopes, not conversations, and remains disabled. `checkpoints.enabled` (filesystem rollback) also remains off; this workflow's handoff files are separate. Existing settings for model/provider/auth and the running gateway are unchanged. Files under the mounted `/opt/data` survive container recreation, but an external backup is still needed for disaster recovery.

**Limits:** The launcher makes a native fresh session only when launched interactively; it is not a scheduler or an automatic boundary inside an already-running task. The checkpoint instruction in the seed is guidance, not an enforced completion hook; run the checkpoint command yourself if the agent stops early or fails. The assistant can still load global memory, skills metadata, or repo rules; 'only relevant project information' does not mean a zero-context system prompt. Starting a new session avoids old task transcript reuse, but its prompt-cache and Codex quota effects are workload-dependent.
