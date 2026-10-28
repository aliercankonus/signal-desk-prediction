# Signal Desk operations runbook

This is a procedure for the **already approved** VPS release, not a way to select
or install a new release. The agent's writable development checkout and the
root-owned deployment checkout are separate. SSH exposes only `status`,
`validate` and `deploy`; it cannot fetch, switch branches, promote a commit,
read arbitrary host files or open a shell. See [INSTALLATION.md](../INSTALLATION.md)
for the separate VPS root-terminal approval and activation procedure. Do not
run that procedure through the restricted SSH key.

## 0. Initial access and configuration staging (operator-only setup)

These steps precede the root-terminal release approval in
[INSTALLATION.md](../INSTALLATION.md). They are templates, **not commands run by
this documentation change**. Use reviewed host/account/path values only in the
private operator record; do not paste them, public keys tied to infrastructure,
private keys or `.env` contents into Git. Never replace a pre-existing
`authorized_keys` file automatically. If the dedicated account/key already
exists, verify it rather than recreating it.

**Agent-local dedicated key:** use an exclusive key path, restrictive modes and
an operator-chosen public comment. The public `.pub` file is transferred to the
VPS operator over a trusted channel; the private key never leaves the agent's
private storage. Choose key passphrase/agent handling for the operator's access
model (an unattended `BatchMode=yes` client needs a usable unlocked identity).

```bash
set -euo pipefail
umask 077
SSH_KEY=/path/to/private/dedicated-key
KEY_COMMENT=your-dedicated-public-key-comment
install -d -m 700 "$(dirname -- "$SSH_KEY")"
test ! -e "$SSH_KEY" && test ! -e "$SSH_KEY.pub"
ssh-keygen -t ed25519 -f "$SSH_KEY" -C "$KEY_COMMENT"
chmod 600 "$SSH_KEY"
```

**VPS root terminal:** select an account dedicated to this gateway and a
privately staged, independently reviewed *public* key file. The following
illustrates the initial **hostname-only** restriction, before the separate
gateway activation. Stop rather than overwrite an existing account's keys or
silently remove a `from=`/expiry restriction. The root operator must also
review host-wide `sshd` and sudo policy; this key line alone is not a complete
authorization audit.

```bash
set -euo pipefail
umask 077
AGENT_USER=your-dedicated-ssh-user
PUBLIC_KEY_FILE=/root/path/to/staged-public-key.pub
KEY_COMMENT=your-dedicated-public-key-comment
TRUSTED_KEY_FINGERPRINT=SHA256:independently-verified-agent-key
if id "$AGENT_USER" >/dev/null 2>&1; then
  echo 'Dedicated account already exists; stop and review it manually' >&2
  exit 1
fi
test -f "$PUBLIC_KEY_FILE" && test ! -L "$PUBLIC_KEY_FILE"
actual=$(ssh-keygen -lf "$PUBLIC_KEY_FILE" -E sha256 | awk '{print $2}')
test "$actual" = "$TRUSTED_KEY_FINGERPRINT"
read -r key_type key_data key_comment < "$PUBLIC_KEY_FILE"
[[ "$key_type" == ssh-ed25519 && "$key_comment" == "$KEY_COMMENT" ]]
[[ "$key_data" =~ ^[A-Za-z0-9+/]+={0,2}$ ]]
useradd --create-home --shell /bin/bash "$AGENT_USER"
AGENT_HOME=$(getent passwd "$AGENT_USER" | cut -d: -f6)
AGENT_GROUP=$(id -gn "$AGENT_USER")
install -d -o "$AGENT_USER" -g "$AGENT_GROUP" -m 700 "$AGENT_HOME/.ssh"
auth="$AGENT_HOME/.ssh/authorized_keys"
test ! -e "$auth" && test ! -L "$auth"
printf 'restrict,command="/usr/bin/hostname" %s %s %s\n' \
  "$key_type" "$key_data" "$key_comment" > "$auth"
chown "$AGENT_USER:$AGENT_GROUP" "$auth"
chmod 600 "$auth"
```

**Pin the host key locally:** obtain the VPS *host public key* from the operator
(for example `/etc/ssh/ssh_host_ed25519_key.pub` in a trusted host terminal).
Compare its SHA-256 fingerprint against an independently trusted value; a raw
`ssh-keyscan` result or a first-connection prompt is not a trust anchor. Then
write exactly the verified host/key pair to a private known-hosts file, without
overwriting an existing pin. Use the same `SSH_HOST` string in SSH commands.

```bash
set -euo pipefail
umask 077
SSH_HOST=your-reachable-host-or-gateway
SSH_KNOWN_HOSTS=/path/to/private/known-hosts
HOST_PUBLIC_KEY_FILE=/path/to/operator-provided-host-ed25519.pub
TRUSTED_HOST_FINGERPRINT=SHA256:independently-verified-value
actual=$(ssh-keygen -lf "$HOST_PUBLIC_KEY_FILE" -E sha256 | awk '{print $2}')
test "$actual" = "$TRUSTED_HOST_FINGERPRINT"
read -r host_type host_data _ < "$HOST_PUBLIC_KEY_FILE"
test "$host_type" = ssh-ed25519
test ! -e "$SSH_KNOWN_HOSTS" && test ! -L "$SSH_KNOWN_HOSTS"
install -d -m 700 "$(dirname -- "$SSH_KNOWN_HOSTS")"
printf '%s %s %s\n' "$SSH_HOST" "$host_type" "$host_data" > "$SSH_KNOWN_HOSTS"
chmod 600 "$SSH_KNOWN_HOSTS"
```

The first SSH test uses `IdentitiesOnly=yes`, `BatchMode=yes`,
`StrictHostKeyChecking=yes` and this pinned file; the forced key runs only
`/usr/bin/hostname`. A successful hostname response proves access to that
restricted diagnostic, **not** deployment permission. With the locally pinned
host key and dedicated key, test only that diagnostic:

```bash
SSH_USER=your-dedicated-ssh-user
ssh -T -i "$SSH_KEY" -o IdentitiesOnly=yes -o BatchMode=yes \
  -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$SSH_KNOWN_HOSTS" \
  -o ConnectTimeout=10 "$SSH_USER@$SSH_HOST" hostname
```

Record the exit code and returned identity privately. Do not attempt
`validate` or `deploy` before separate root-terminal release approval and
gateway activation.

**Initial configuration staging (VPS root terminal):** privately review the
existing project `.env` and active `config/config.yaml`. Preserve their project
name, bind/port and data-volume namespace, and require `mode: paper` with
`execution_enabled: false`. Copy only operator-approved files to a *new* root-only
staging tree outside Hermes mounts; do not print contents, use shell tracing or
copy an example over active configuration. In this generic template, `STAGING`
becomes `OLD_HOST_CHECKOUT` in the approval procedure. The canonical preflight
there checks source ownership, modes and mount isolation before further copying.

```bash
set -euo pipefail
umask 077
EXISTING_CONFIG_CHECKOUT=/path/to/operator-reviewed-existing-host-checkout
STAGING=/root/path/to/new-approved-config-staging
test ! -e "$STAGING" && test ! -L "$STAGING"
install -d -o root -g root -m 700 "$STAGING" "$STAGING/config"
install -o root -g root -m 600 "$EXISTING_CONFIG_CHECKOUT/.env" "$STAGING/.env"
install -o root -g root -m 600 \
  "$EXISTING_CONFIG_CHECKOUT/config/config.yaml" "$STAGING/config/config.yaml"
# Review values privately; never emit the files to a public log.
```

See [OPERATIONS_LEDGER.md](OPERATIONS_LEDGER.md) for dated, provenance-labelled
operational evidence. Key/user setup and protected-release approval are
operator-reported unless directly inspected in a trusted host terminal.

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
