# Dormant issue #45 GitHub inbox (review-only)

The separately reviewed [hourly :30 Europe/Amsterdam scheduler](HOURLY_SCHEDULER.md) is dormant source, not an installed timer, and does not alter this inbox's one-task authority.

This is **not installed, enabled, scheduled or tested on the VPS**. It is a one-shot signed-grant adapter to the existing `BridgeQueue -> Bridge.once -> HermesAgent` path, not a second executor or repository-wide watcher. Merge decisions remain with the manager; no child may merge/deploy, execute root/host actions, handle credentials or invoke another inbox. The current #41 one-shot package and historical queue/journals are preserved. Incorporate this dormant entry point into #41's **single** reviewed operator handoff after merge; do not silently replace its independent runner pin `00acd27132b68264ee2ab1692d3024f09c640c6d`. Because this implementation changes runner source, a new reviewed runner pin and private interpreter context are required before any new task. The already frozen #43 task cannot be automatically assigned to an instruction with different scope.

## Exact authority boundary

An operator enrolls only `aliercankonus/signal-desk-prediction`, issue comments on **#41 and #45**, a particular pre-approved *development-only* Bridge task issue, immutable authorization identity, runner SHA and public Ed25519 verifier. The manager signing key must be provisioned to a **separate trusted manager automation**, never to the Hermes worker/home/container; the inbox receives only its public key. Both actors currently post with Ali's GitHub login, so author/label/`GO` text is not authority. A new manager instruction is first posted as a plain comment after enrollment, then the manager automation posts a distinct JSON grant comment signed over its canonical payload. The private task authorization remains a separate explicit gate; a signature cannot expand it. Without separately reviewed signing-key provisioning and the matching frozen task, no instruction is eligible. Do not place the signer key, a Git token or provider state in the repository or worker mounts.

Grant comment, with **no** surrounding prose/quote:

```json
{"signal_desk_grant_v1":{"payload":{"v":1,"repo":"aliercankonus/signal-desk-prediction","issue":41,"instruction_id":123,"instruction_sha256":"<sha256 of exact instruction UTF-8 body>","task_issue":43,"authority_identity":"<Policy.identity>","runner_commit":"<reviewed runner SHA>","scope":"development-only"},"signature":"<base64 Ed25519 signature>"}}
```

The eligible instruction body is exactly `RUN FROZEN DEVELOPMENT TASK #<task_issue> AUTH <Policy.identity>` (no surrounding prose). It is a trigger for that already frozen task, not arbitrary issue text sent to a child. Any different manager request needs a new reviewed task authorization and enrollment, not a broader parser. The signed bytes are `json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')`. Signing can use `openssl pkeyutl -sign -inkey <manager-private-key> -rawin -in <canonical-payload-file> -out <signature-file>` **only in the manager's protected environment**; its automation must post the grant, not Ali. The worker verifies the signature with `openssl pkeyutl -verify -pubin -rawin` and pinned public-key digest. Both instruction and grant must have `created_at == updated_at`, instruction ID must be later than the enrollment starting cursor and earlier than the grant, and its fetched body digest must match. Edits, replies, old smoke comments, self-generated status JSON, unsigned text and different issue/scope are inert. No manager signing service or key is provisioned by this PR.

## Explicit future operator enrollment (NOT EXECUTED)

One private `0600` JSON enrollment outside checkout, with trusted private ancestors and exact fields: `repo`, `issues` (`[41,45]`), `task_issue`, `runner`, `runner_commit`, `queue`, `authorization`, `context`, `public_key`, `public_key_sha256`, `interval_seconds` (minimum `300`). `queue` must be the dedicated Bridge queue, `state` must be its sibling `github-inbox`, and `authorization`/`context` are the already reviewed private files. The public PEM is held in an owner-private file so its replacement fails the digest gate. Reject nonempty queue, changed runner or changed authority; do not reuse the historical worker root. `enroll` snapshots each issue's latest immutable comment ID and starts **disabled**. Confirm the exact UTC `--start` is the enrollment instant (not an earlier timestamp); never reset an existing cursor or delete state to replay comments. Create the queue only under separately reviewed #41 preparation; this PR does not do so.

After merge, separate root/operator approval, installed immutable runner and matching private authorization/context, the operator may review/instantiate these commands at the verified runtime's own paths (no hardcoded VPS path in the code):

```sh
PYTHONPATH=src:autonomous-development python -B ops/github_inbox/inboxctl.py enroll --enrollment "$PRIVATE_ENROLLMENT" --state "$PRIVATE_INBOX_STATE" --start "$UTC_ENROLLMENT_INSTANT"
PYTHONPATH=src:autonomous-development python -B ops/github_inbox/inboxctl.py doctor --enrollment "$PRIVATE_ENROLLMENT" --state "$PRIVATE_INBOX_STATE"
# STOP: enrollment is disabled; no polling/child has been started.
```

`enable` is a later, separately reviewed operator action, **not** an environment variable bypass. The reviewed [hourly :30 Europe/Amsterdam scheduler](HOURLY_SCHEDULER.md) is a dormant non-LLM source entry for a future **dedicated persistent isolated worker**, not the transient one-shot worker or the existing shared Hermes gateway/profile. Never start it from this PR or install it in the current profile. Polling remains bounded to two feeds × five pages × 100 comments, 15-second HTTP deadlines and 128-KiB responses. Conditional ETag is used only for a complete first page; overfull history fails closed. Rate limits honor bounded Retry-After/reset headers, otherwise wait at least five minutes and record availability unknown. There are no model calls on empty polls. One local inbox lock and fsynced claim precede ack, running receipt, enqueue and dispatch; the scheduler holds a separate private lock for its entire process lifetime. A claimed/blocked queue entry is never automatically relaunched. Sanitized receipts are read back by exact GitHub comment ID; the Bridge independently owns task issue publications and draft PR verification.

```sh
# Later authorized enable and manual diagnostic tick ONLY; not the hourly scheduler:
PYTHONPATH=src:autonomous-development python -B ops/github_inbox/inboxctl.py enable --enrollment "$PRIVATE_ENROLLMENT" --state "$PRIVATE_INBOX_STATE"
PYTHONPATH=src:autonomous-development python -B ops/github_inbox/inboxctl.py tick --enrollment "$PRIVATE_ENROLLMENT" --state "$PRIVATE_INBOX_STATE"
# Rollback/disable only the owned enrollment; preserve state and all runs:
PYTHONPATH=src:autonomous-development python -B ops/github_inbox/inboxctl.py disable --enrollment "$PRIVATE_ENROLLMENT" --state "$PRIVATE_INBOX_STATE"
```

Do **not** paste the future enable/tick block before reviewed merge, provisioning, #41 operator approval and exact host-path inspection. Never run `tick` from a Hermes child or a second worker. Preserve the state, queue, Bridge journals, worktrees and private recovery checkpoints in a consistent, owner-private off-host backup; never export credentials or raw private diagnostics to GitHub. `doctor` is read-only; a claimed or ambiguous run is reconciled **read-only** with Bridge doctor/reconcile, local Git and exact remote PR/CI before any separately approved continuation. `disable` does not terminate an already running child; exclusive operator coordination is required. No automated retry, quota-reset guess or historical #26/#27/#30/#34/#37 recovery.

## Recovery contract delivery

`HermesAgent.run` reads the reviewed `docs/HERMES_SESSION_RECOVERY.md` from its own pinned runner, checks its committed bytes in production and embeds the full text plus digest in the trusted task-start prompt **before** issue prose. It creates a private identity file and a fsynced `child-intent` checkpoint before the child command for real 32-hex run IDs. The trusted prompt includes the explicit Python `signal_desk.task_bridge.recovery` command for pre/post tests, commit and push; the supervisor writes `child-completed` and `pushed-head-verified` only after its corresponding observations. These checkpoint stages are self-reports; Bridge journals/remote receipts remain authoritative. An abrupt child exit cannot produce a final response; the existing Bridge diagnostic/status boundaries and the inbox's preserved claim block redispatch. The pinned old #41 runner lacks this file and must not be used as if it contains the contract. See the runbook for read-only fresh-session reconciliation and continuation authority.
