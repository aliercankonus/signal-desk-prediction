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

## Restricted SSH host-command gateway (operator approval, separate from install)

Keep the Hermes development checkout writable and unchanged. It is **never** the
host deployment checkout. Only the VPS root operator may prepare a second,
root-owned checkout under `/srv/signal-desk-releases/`, outside every mount
visible to the Hermes container. The checkout, its ancestors, Git metadata,
code and configuration must be root-owned and not group/world writable. The
release guard checks these conditions, the pinned agent-container mounts and the
existing project volume before every operation. Do not change ownership of
the development checkout.

In a **VPS root terminal**, select a reviewed **full 40-character commit SHA**,
trusted Git remote and existing Compose project. Stage the operator-approved
`.env` and `config/config.yaml` in a root-only directory outside Hermes mounts.
Copy them from the existing host configuration into a root-only staging tree
first, after private review; point `OLD_HOST_CHECKOUT` at that staged tree. The
preflight refuses symlinks, writable ancestry or non-root-owned source files.
Do not print their contents or turn on shell tracing. The project, port and bind values
in `.env` are retained. Example with configurable values (not an agent command):

```bash
set -euo pipefail
umask 077
APPROVED_SHA=your-reviewed-full-commit-sha
[[ $APPROVED_SHA =~ ^[0-9a-f]{40}$ ]] || { echo 'Full reviewed SHA required' >&2; exit 1; }
REMOTE=https://github.com/your-org/signal-desk-prediction.git
DEPLOY_DIR="/srv/signal-desk-releases/$APPROVED_SHA"
APPROVED_CONFIG=/etc/signal-desk/operator-config
SETTINGS="/etc/signal-desk/releases/$APPROVED_SHA.json"
OLD_HOST_CHECKOUT=/path/to/root-only-staged-existing-host-config
AGENT_CONTAINER=your-Hermes-container-name
PROJECT=your-existing-COMPOSE_PROJECT_NAME
EXPECTED_HOST=$(hostname)
# Independent preflight before creating the release or copying secrets.
python3 - "$DEPLOY_DIR" "$AGENT_CONTAINER" "$OLD_HOST_CHECKOUT" <<'PY'
import json, os, pathlib, stat, subprocess, sys
release = pathlib.Path(sys.argv[1])
for path in (release, *release.parents):
    if not path.exists():
        continue
    mode = os.lstat(path)
    assert mode.st_uid == 0 and not mode.st_mode & 0o022 and not stat.S_ISLNK(mode.st_mode), path
for source in (pathlib.Path(sys.argv[3]) / '.env', pathlib.Path(sys.argv[3]) / 'config/config.yaml'):
    for path in (source, *source.parents):
        mode = os.lstat(path)
        assert mode.st_uid == 0 and not stat.S_ISLNK(mode.st_mode), path
        assert not mode.st_mode & (0o077 if path == source else 0o022), path
protected_destinations = [pathlib.Path('/usr/local/libexec/signal-desk'), pathlib.Path('/etc/signal-desk'), pathlib.Path('/etc/sudoers.d')]
for destination in protected_destinations:
    for path in (destination, *destination.parents):
        if not path.exists():
            continue
        mode = os.lstat(path)
        assert mode.st_uid == 0 and not mode.st_mode & 0o022 and not stat.S_ISLNK(mode.st_mode), path
containers = [sys.argv[2]] + subprocess.check_output(['docker', 'ps', '-aq', '--filter', 'name=hermes-agent'], text=True).splitlines()
for container in containers:
    mounts = json.loads(subprocess.check_output(['docker', 'inspect', '--format', '{{json .Mounts}}', container], text=True))
    for mount in mounts:
        source = pathlib.Path(mount['Source']).resolve()
        for path in (release, pathlib.Path(sys.argv[3]).resolve(), *protected_destinations):
            assert not (path == source or path.is_relative_to(source) or source.is_relative_to(path)), source
PY
install -d -o root -g root -m 700 /srv/signal-desk-releases /etc/signal-desk /etc/signal-desk/releases "$APPROVED_CONFIG"
install -o root -g root -m 600 "$OLD_HOST_CHECKOUT/.env" "$APPROVED_CONFIG/.env"
install -o root -g root -m 600 "$OLD_HOST_CHECKOUT/config/config.yaml" "$APPROVED_CONFIG/config.yaml"
git clone --no-checkout -- "$REMOTE" "$DEPLOY_DIR"
git -C "$DEPLOY_DIR" checkout --detach "$APPROVED_SHA"
test "$(git -C "$DEPLOY_DIR" rev-parse HEAD)" = "$APPROVED_SHA"
test -z "$(git -C "$DEPLOY_DIR" status --porcelain --untracked-files=all)"
# Independent bootstrap preflight: no code from the candidate checkout runs yet.
python3 - "$DEPLOY_DIR" "$AGENT_CONTAINER" <<'PY'
import json, os, pathlib, stat, subprocess, sys
release = pathlib.Path(sys.argv[1])
for path in (release, *release.parents):
    mode = os.lstat(path)
    assert mode.st_uid == 0 and not mode.st_mode & 0o022 and not stat.S_ISLNK(mode.st_mode), path
for root, dirs, files in os.walk(release, followlinks=False):
    for path in (pathlib.Path(root) / name for name in dirs + files):
        mode = os.lstat(path)
        assert mode.st_uid == 0 and not mode.st_mode & 0o022 and not stat.S_ISLNK(mode.st_mode), path
PY
install -d -o root -g root -m 755 /usr/local/libexec/signal-desk
install -o root -g root -m 755 "$DEPLOY_DIR/scripts/host_release_guard.py" /usr/local/libexec/signal-desk/release-guard.py
# The root-owned verifier is now separate from the candidate checkout.
bash "$DEPLOY_DIR/scripts/prepare-host-release.sh" --dir "$DEPLOY_DIR" \
  --commit "$APPROVED_SHA" --config-dir "$APPROVED_CONFIG" \
  --agent-container "$AGENT_CONTAINER" --project "$PROJECT" \
  --expected-host "$EXPECTED_HOST" --settings "$SETTINGS"
```

Clone/checkout is an **explicit root-terminal action**, never an SSH gateway
operation. The standalone preflight verifies the reviewed SHA, root-owned
non-replaceable paths, and mount isolation **before any checkout Python or shell
code is executed as root**. The guard is installed independently as a root-owned
copy; preparation and activation invoke that copy, never the candidate guard.
Use a new path per release; neither the old checkout nor Docker
volumes are removed or re-owned. `prepare-host-release.sh` rejects an unclean or
wrong checkout, exposed/writable paths, unapproved configuration, project
mismatch, a missing/changed agent container, or a missing existing API service
using the named project volume. It pins the volume mountpoint and creation time
and refuses a replaced volume on later operations. It copies config with mode 0600,
checks paper mode and disabled execution, then writes a root-only manifest with
the full SHA, project, host, container ID and config hashes. It does not start
Docker services, alter SSH authorization or log secrets. If a step fails,
inspect the partial root-owned checkout; no automatic rollback is promised.

Only after reviewing that protected checkout and manifest, the root operator
may **separately** install the forced-command gateway:

```bash
AGENT_USER=your-dedicated-ssh-user
KEY_COMMENT=your-public-key-comment
KEY_FINGERPRINT=SHA256:your-independently-verified-key-fingerprint
bash "$DEPLOY_DIR/scripts/install-host-gateway.sh" --settings "$SETTINGS" \
  --agent-user "$AGENT_USER" --key-comment "$KEY_COMMENT" \
  --key-fingerprint "$KEY_FINGERPRINT"
```

Derive the fingerprint from a trusted public key outside the VPS, not merely
from `authorized_keys`. The activation script checks **each shell script
separately** with `bash -n` before touching authorization. It requires one
hostname-only restricted ed25519 key, refuses other key options, and publishes
its new forced command before the three exact sudoers privileges. Activation
is one-shot: an existing or partially activated gateway is never overwritten;
root must inspect and resolve it separately. Installed
executables and settings are root-owned, not writable by Hermes or the SSH
account. It does not grant Docker-group membership or unrestricted sudo.
Inspect any partial state after failure. Existing sshd policy, alternate keys
and prior sudo grants need separate host-side review.

Once the root operator has installed and tested the gateway, the agent can use
exactly `status`, `validate` or `deploy`, with no flags. The installed verifier
checks the approved full SHA, root ownership, protected ancestry, Hermes mount
isolation, clean code and approved config hashes **before** running Compose or
repository code. SSH has no fetch, checkout, release selection or promotion
operation. `validate` builds and tests the collector; `deploy` runs the existing
bounded paper-only deploy script against the **same** Compose project/volume.
These are future procedures, not evidence that a host setup has occurred.

**Security boundary:** Docker-backed validation/deployment executes the approved
repository code with host privileges. Command filtering is not a sandbox. A
clean Git working tree is insufficient without commit and path approval. Keep
paper mode and `execution_enabled=false`; preserve the old checkout and data
volume. Clean-host installation and restore remain unverified.

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
