# Issue #22 task bridge — review-only operator guide

This PR adds **source code and inert local tests**, not an installed or running worker. The existing deployment is unchanged. Do not add a cron job, gateway trigger, daemon, webhook, or persistent polling configuration as part of this PR. The gateway may already have a cron ticker; this bridge creates no job.

## Verified boundary

- The only authorized bootstrap task is `aliercankonus/signal-desk-prediction` issue **#22**, whose frozen UTF-8 body SHA-256 is `c855863cbf42d0941546954de58657aaa35394e3b4c2059910de8d0570b7d181`. The pinned development base is `a930a3c715635341e62538a3cc15a260162f6be9`. A body edit or closed issue blocks a new run. Comments, labels and task prose grant no independent permission.
- Installed Hermes Agent `v0.22.5` advertises `hermes chat --query-file PATH --oneshot --quiet --in DIR --max-turns N --run-budget SECONDS`. The adapter checks those flags against installed help. The bridge's **real agent/PR pipeline has not been exercised**; the end-to-end tests use fakes, and the process-cleanup tests launch only synthetic Python children. The development credential helper is available, but prompt restrictions do not revoke any GitHub or shell authority the operator's account actually has.
- The manually invoked `once` command is one bounded attempt. It validates the source repository and actual pinned commit object **before public progress**, then creates one pinned-base branch/worktree and a private SQLite journal under a required outside-git state directory. Its nonblocking `flock` only excludes another worker using **that same directory on this machine**; GitHub comments are not distributed claims. At most one run is retained in that directory (eight journal transitions and four publication attempts maximum). No automatic retry or issue discovery exists. The agent's stdout/stderr are discarded, not stored; the private prompt is bounded and retained for diagnosis.
- Run identity, repository/issue number, branch/worktree and `queued`/`running` progress are durable before the agent child starts. Journaled comment receipt IDs distinguish confirmed from ambiguous status publication. An interrupted, timed-out or ambiguous child/push/publication remains blocked; neither a retry nor a `doctor`/`reconcile` call resumes it. `reconcile` compares confirmed receipt IDs and exact status payloads with comments from the authenticated publishing account, and checks the draft PR/CI and pinned-base ancestry by read-only API calls; mismatches and unconfirmed publications remain visible and blocked. External effects are **not exactly once**. A verified draft PR, exact head and exact-head check/workflow status are required before `review-ready` is published. `unknown` or pending CI is reported as such, never called green. Status comments are allowlisted JSON with run ID/base and, if verified, PR URL/head/CI; raw child output, issue comments, secrets, private paths and host logs stay off GitHub.

## Read-only preflight (no activation)

Choose `STATE_DIR` privately **outside every repository, worktree, data volume and protected release**. A pre-existing directory must be owned by the development user and mode `0700`; never reuse another worker's state directory or remove an ambiguous journal. Replace `REPO_DIR` with the reviewed development checkout of this repository. These commands do not create a worker:

```sh
REPO_DIR=/path/to/reviewed/development/checkout
STATE_DIR=/path/to/private/issue22-bridge-state
hermes --version
hermes chat --help
hermes cron status
git -C "$REPO_DIR" remote get-url origin
git -C "$REPO_DIR" cat-file -t a930a3c715635341e62538a3cc15a260162f6be9
git -C "$REPO_DIR" show-ref --verify refs/heads/issue-22-bridge || true
PYTHONPATH="$REPO_DIR/src" python -m signal_desk.task_bridge doctor --state "$STATE_DIR"
PYTHONPATH="$REPO_DIR/src" python -m signal_desk.task_bridge reconcile --state "$STATE_DIR"
```

`doctor` reads only local state; `reconcile` reads the existing journal and, when present, the matching draft PR and exact-head CI through the approved GitHub API. Neither authorizes a retry or writes a comment. If a prior run is `blocked`, inspect its private journal/worktree and the GitHub branch/PR separately; do not delete state, reset/clean the checkout, or rerun `once`. Obtain a new explicit authorization for a recovery procedure rather than inventing an exactly-once retry.

## STOP — separate one-time activation after code review and authorization

The command below is a **proposal**, not run in this development task. It is not a reason to repeat issue #22 once its task has already been delivered; a future issue needs its own reviewed, pinned authorization. Before any later invocation, review the draft PR and its CI, confirm no worker/state-dir competitor, ensure the issue body and base still match, verify repository origin is precisely `https://github.com/aliercankonus/signal-desk-prediction.git`, and verify the fixed branch `issue-22-bridge` and target worktree are absent. Run only from the trusted development user with the actually approved credentials. `--execute-hermes` is explicit; the issue body itself does not supply that authorization.

```sh
PYTHONPATH="$REPO_DIR/src" python -m signal_desk.task_bridge once \
  --state "$STATE_DIR" --source "$REPO_DIR" --execute-hermes
```

To stop a foreground invocation, send **SIGTERM** to its bridge process, then run read-only `doctor` and `reconcile` and inspect the worktree, branch and draft PR. The adapter attempts bounded process-group termination for SIGTERM/timeout; an unkillable process, SIGKILL or host failure can leave ambiguity. Do not infer that an aborted command rolled back GitHub effects. No merge, deployment, privileged host action, collector startup, operator-data migration or trading execution is part of this bridge.
