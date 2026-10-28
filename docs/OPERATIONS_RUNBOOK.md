# Signal Desk operations runbook

This is a procedure for the **already approved** VPS release, not a way to select
or install a new release. The agent's writable development checkout and the
root-owned deployment checkout are separate. SSH exposes only `status`,
`validate` and `deploy`; it cannot fetch, switch branches, promote a commit,
read arbitrary host files or open a shell. See [INSTALLATION.md](../INSTALLATION.md)
for the separate VPS root-terminal approval and activation procedure. Do not
run that procedure through the restricted SSH key.

## Safety and prerequisites

- Binance BTCUSDT spot, `mode: paper`, `execution_enabled: false`. The API's
  `ready_for_enter=false` is not a trade permission. Real orders are out of scope.
- Confirm the operator-approved full commit SHA, root-owned protected checkout,
  unchanged Compose project and existing data volume. The installed verifier
  checks these on every SSH operation; a clean Git tree by itself is insufficient.
- Have the dedicated private key and independently pinned SSH host key in local,
  non-repository files. Set the host and user for this deployment without storing
  those identities or secrets in Git. Do not turn on shell tracing around secrets.
- Keep the collector idle unless a *separately approved, bounded* collection test
  is intended. Never run two collectors against the same data volume. Neither
  `status` nor `validate` starts continuous collection.
- Do not remove orphan containers, prune volumes, run `down -v`, reset Git, edit
  approved configuration, or grant Docker-group/unrestricted sudo access.

```bash
SSH_HOST=your-reachable-host-or-gateway
SSH_USER=your-dedicated-ssh-user
SSH_KEY=/path/to/dedicated-private-key
SSH_KNOWN_HOSTS=/path/to/pinned-known-hosts
```

Run **one exact operation** at a time; do not append flags or shell commands.
Capture the exit status in the same shell. `ConnectTimeout` limits connection
setup, not the duration of a build or test; let validation/deployment finish.

## 1. Read-only status

```bash
ssh -T -i "$SSH_KEY" -o IdentitiesOnly=yes -o BatchMode=yes \
  -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$SSH_KNOWN_HOSTS" \
  -o ConnectTimeout=10 "$SSH_USER@$SSH_HOST" status
status_rc=$?
printf 'STATUS_EXIT_CODE=%s\n' "$status_rc"
```

Expect `HOST=... PROJECT=...` and Compose service state. A healthy API is a
runtime check, not proof of data correctness, paper strategy readiness or the
identity of a future release. If status fails, stop; see
[TROUBLESHOOTING.md](TROUBLESHOOTING.md). Do not work around a guard failure.

## 2. Validation gate (before deploy)

```bash
ssh -T -i "$SSH_KEY" -o IdentitiesOnly=yes -o BatchMode=yes \
  -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$SSH_KNOWN_HOSTS" \
  -o ConnectTimeout=10 "$SSH_USER@$SSH_HOST" validate
validate_rc=$?
printf 'VALIDATE_EXIT_CODE=%s\n' "$validate_rc"
```

Validation checks Compose syntax, builds the collector image, validates the
approved config and schemas **inside that image**, then runs the **full** pytest
suite there. Record the actual `schemas_ok`, config version, paper mode, pytest
count and SSH exit code. A Git executable is required inside the image for the
release-guard regression fixtures. If any stage fails, stop; do not deploy or
modify the protected checkout to make tests pass. Local fake-Docker tests are
not a substitute for the host-image run.

## 3. Explicitly approved deployment

Only after a successful validation and an operator's explicit go-ahead, run:

```bash
ssh -T -i "$SSH_KEY" -o IdentitiesOnly=yes -o BatchMode=yes \
  -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$SSH_KNOWN_HOSTS" \
  -o ConnectTimeout=10 "$SSH_USER@$SSH_HOST" deploy
deploy_rc=$?
printf 'DEPLOY_EXIT_CODE=%s\n' "$deploy_rc"
```

The reviewed deploy script checks the host and project, refuses a running
collector, builds API/collector images, repeats config/schema and full pytest
checks, runs one REST snapshot and a bounded 25-event WebSocket stream, then
starts **only the API** with `--wait` and checks paper-only health. It does not
promote code or enable continuous collection or real execution. Require
`DEPLOY_OK`, SSH exit code `0`, successful smoke results and healthy API;
otherwise stop at the reported `DEPLOY_FAILED stage=...` without automatic
repair or retry. An API restart is an expected side effect of successful deploy.

Each run writes a host-local `runtime/install/run.*/deploy.log` and, on success,
`manifest.json` under the protected release checkout. Record the **exact paths
printed by that run**, not a guessed directory. The manifest contains commit,
image IDs, config hash, project/volume and smoke status; it is not a substitute
for inspecting the actual file via an authorized root-side review. Do not copy
host-private logs, settings or secrets into a public issue or PR.

## 4. Read back runtime status

After successful deploy, repeat the read-only `status` command and capture its
exit code. Confirm the API is healthy on the intended loopback binding. This
checks service state; it does not independently read the manifest or establish
24-hour collection, replay parity, restore, economic performance or a complete
paper ledger. Any new commit needs its own root-terminal protected-release
approval; the SSH gateway cannot select it.

## Evidence and scope

Record the operation, reviewed SHA, UTC time, exit code, schema/test counts,
smoke outcome, API health, and the exact local manifest/log paths in the private
operator record. Keep public [PROJECT_STATE.md](../PROJECT_STATE.md) free of
host-specific identities and private command transcripts. The gateway runs
approved repository code through Docker with host privileges: command filtering
is **not** a sandbox. See [docs/COMMANDS.md](COMMANDS.md) for generic manual
commands and [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for fail-closed diagnostics.
