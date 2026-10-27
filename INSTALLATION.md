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
