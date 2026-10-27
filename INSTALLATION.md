# Installation in one operation

## Existing checkout

From the repository directory in the VPS host terminal:

```bash
bash scripts/install.sh
```

From another directory:

```bash
bash /path/to/signal-desk-prediction/scripts/install.sh
```

The existing checkout is reused; it is not recloned and its branch is not changed
automatically. To explicitly select another ref:

```bash
bash scripts/install.sh --ref COMMIT_SHA
```

Ref updates stop if code changes are present. Git stops if a checkout conflicts
with active config; config is not reset and no force/reset is used.

## New Ubuntu server

Automatic Docker prerequisites support Ubuntu 22.04/24.04, root/sudo and a systemd
host. A working Docker engine is not reinstalled or restarted.
The following single shell operation downloads the full script before executing it:

```bash
sudo bash -c 'set -eu; command -v curl >/dev/null || { apt-get update; apt-get install -y ca-certificates curl; }; f=$(mktemp); trap "rm -f \"$f\"" EXIT; curl -fsSL https://raw.githubusercontent.com/aliercankonus/signal-desk-prediction/main/scripts/install.sh -o "$f"; bash "$f" --install-docker'
```

The default destination is /opt/signal-desk-prediction. For another path/ref, pass
`--dir /chosen/path --ref COMMIT_SHA` to the downloaded script. When run from a
checkout, the script finds its existing location. Prefer a full commit SHA over a
branch for repeatable code versions. Docker/OS packages and base image tags are not
bit-for-bit locked; actual Git/image/config/Python/dependency identities are recorded
in the local manifest.

## Sequence and success criteria

1. Host/container and optional expected-host checks.
2. Docker daemon, Compose, Buildx and --wait support; Git and bootstrap capacity.
3. Verify the existing repository identity or clone into an empty destination.
4. Create missing config/.env; preserve active files. Initialize a fresh clone's
   versioned config from the current config.example.yaml.
5. Validate Compose and build api/collector images.
6. Validate config/schemas and run the full pytest suite inside a container.
7. By default, run a public Binance snapshot and 25-record stream smoke test.
8. Start only the API with --wait; verify paper mode, disabled execution and BTCUSDT health.
9. Write a local manifest and command log; report DEPLOY_OK.

Stop on failure before proceeding to later stages. Deployment stops if a collector
for this project is running. The installer does not enable continuous collection
or maintenance; it completes API installation and short checks. It does not establish
1h/24h soak, data/replay parity, model/ledger/PnL or Time Machine acceptance.
Use `--no-smoke` for closed-network tests that do not require live smoke; the manifest
explicitly records smoke_skipped and does not establish live-feed acceptance.

## Config, port and project

A new installation binds to 127.0.0.1:8080. Explicitly choose --bind 0.0.0.0 if external
access is required; TLS/auth setup is outside the installer's scope.

```bash
bash scripts/install.sh --project signal-desk-prediction --port 8080 --bind 127.0.0.1
bash scripts/install.sh --expected-host EXPECTED_HOSTNAME
bash scripts/install.sh --plan
```

If existing .env project/port/bind settings differ, they are not silently changed;
pass matching flags or deliberately edit the file. Other .env lines and
config/config.yaml are preserved. Changing COMPOSE_PROJECT_NAME may select another
Docker volume namespace; retain the old project name to use the same data.

Bootstrap requires 10 GiB free space and at least 1.5 GiB visible MemTotal. These are
not proof of the 100GB/2GB profile's capacity or a retention-duration guarantee.
The collector owns quota/disk HALT checks on the actual data path.

## Installation evidence

Each `runtime/install/run.*/` directory contains:

- deploy.log: executed commands, stdout/stderr, stages and errors.
- git-commit.txt and config.sha256.
- previous-api-image.txt: previous API image ID, if present.
- manifest.json: atomically finalized only after all stages pass; resolved image IDs,
  dependency versions, config hash, Compose project/volume and smoke status.

These are local operational records. The .env contents are not printed;
runtime/.env/active config are excluded from the Docker build context. No automatic
upload to the public repository occurs. Existing Docker data volumes are preserved;
no down -v, prune, reset or remove-orphans is used. API health failure does not
automatically roll back images; logs and the previous image ID are retained.
Returning to a previous image or restoring data requires separate review.

## Restricted SSH host-command gateway (separate one-time root setup)

The gateway is **not** part of the application installer. Copy/review these
repository files in the existing VPS checkout first. In a VPS **root terminal**,
from that checkout, run exactly this command, replacing only the configurable
values with the actual existing account, key comment, independently verified
key fingerprint, Compose project and host:

```bash
bash scripts/install-host-gateway.sh --repo "$PWD" --agent-user "${AGENT_USER:?set dedicated SSH account}" --key-comment "${KEY_COMMENT:?set existing key comment}" --key-fingerprint "${KEY_FINGERPRINT:?set trusted SHA256 public-key fingerprint}" --project "${PROJECT:?set existing COMPOSE_PROJECT_NAME}" --expected-host "$(hostname)"
```

For the existing dedicated key, `KEY_COMMENT=hermes-signal-desk` is the public
key's comment. Derive `KEY_FINGERPRINT` from the trusted public key outside the
VPS (for example, `ssh-keygen -lf /path/to/key.pub -E sha256`); do not trust
only the host's existing authorized_keys entry for key selection. Set `PROJECT`
to the value in the existing `.env`, not a new project name. This script
requires an existing checkout, `.env`, active config, SSH account and exactly
one active authorized key with that comment. It does not
create a user, install Docker, update source or deploy the application. Review
its effects before running: it makes the dedicated account's home and SSH files
root-owned, installs a root-owned forced-command dispatcher and root gateway in
`/usr/local/libexec/signal-desk/`, a root-only settings file under
`/etc/signal-desk/`, and three exact sudoers entries under `/etc/sudoers.d/`.
It replaces the one existing hostname-only authorized key with
`restrict,command=...` and refuses additional active keys or unexpected key
options; it does not silently discard a `from=` restriction. The forced key is
published before sudoers privileges, so an interrupted first installation fails
closed. It checks that the dedicated account cannot write the checkout, Git
metadata, critical inputs or home ancestors. No Docker-group membership or
unrestricted sudo is granted. If the account's home holds other data, inspect
it before changing ownership; use an account dedicated to this gateway.

From the agent container, configure **locally** (never commit the key or host
identity):

```bash
SSH_HOST=your-host-or-reachable-gateway
SSH_USER=your-dedicated-agent-user
SSH_KEY=/path/to/dedicated-private-key
SSH_KNOWN_HOSTS=/path/to/pinned-known-hosts
ssh -T -i "$SSH_KEY" -o IdentitiesOnly=yes -o BatchMode=yes \
  -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$SSH_KNOWN_HOSTS" \
  "$SSH_USER@$SSH_HOST" status
# Replace status with validate or deploy only after reviewing the operation.
```

`status` reports this project's Compose state; `validate` checks Compose,
builds the collector image from the reviewed checkout, then runs application
validation and pytest in disposable collector containers; `deploy`
invokes the existing guarded `scripts/deploy.sh` with the pinned project/host,
builds images, runs bounded smoke tests and starts only the API. Each SSH command
must consist of exactly one word: `status`, `validate` or `deploy`; shell text,
extra flags and other commands are denied. The root gateway requires an existing
`.env` with the same Compose project and active paper-only config. It never uses
`down -v`, prune or a new project name; it does not start continuous collection.
The deployment script retains its own clean-code, running-collector and health
gates and writes evidence under `runtime/install`. Both `validate` and `deploy`
refuse tracked code changes (except active config) and untracked files; synchronize
and commit reviewed code before using them. `status` remains available without a
source update.

**Security boundary:** deployment and validation execute repository code through
Docker with host/root privileges. Filtering SSH commands is not a sandbox for
repository content. Treat the checkout, Dockerfile, Compose file, `.env`, scripts
and dependency sources as privileged inputs: protect them against writes by the
agent account, review the exact commit and changes before `validate` or `deploy`,
and keep host backups. The setup cannot prove clean-host install or restore.
After setup, verify forced-command rejection of unexpected arguments and test
`status` before permitting `validate` or `deploy`. An existing `ForceCommand`,
`AuthorizedKeysCommand`, alternative auth path or pre-existing sudo privilege
needs separate host-side review; this installer does not audit global sshd policy.

## Limitations

- Do not assume host Docker access from Hermes or another agent container.
- Automatic Docker setup does not remove conflicting/existing container runtimes.
- Missing Compose/Buildx on a working Docker host causes a stop rather than engine replacement.
- Root clone/install does not change other users' ownership recursively; Git safe.directory is scoped to one command.
- Existing backup/restore and 200GB migration scripts are skeletons, not verified
  data-transfer procedures. Installation does not establish data/model restore acceptance.
- Shell orchestration has local fake-Docker coverage. The user reported DEPLOY_OK
  from the existing target VPS on 2026-10-27. Independent clean-server installation
  and restore still require separate validation.

See the [command catalog](docs/COMMANDS.md) for all manual setup, diagnostic and
validation commands.
