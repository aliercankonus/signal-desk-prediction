# Installation and validation command catalog

This file preserves the setup/validation steps used so far in a portable form.
Host-specific identities/paths and raw operational output remain in the private log.
Do not blindly rerun this catalog from beginning to end. Normal installation uses
the single installer command in INSTALLATION.md. These commands support diagnostics,
acceptance and reproduction. First select the actual checkout path:

```bash
REPO=/path/to/signal-desk-prediction
cd "$REPO"
PROJECT=signal-desk-prediction
```

## Host and Docker access

```bash
hostname
pwd
ps -p 1 -o comm=
command -v docker
command -v dockerd
systemctl is-active docker
systemctl status docker --no-pager -l
docker --version
docker compose version
docker buildx version
docker info --format '{{.Name}}'
df -h /
free -h
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
ss -ltnp '( sport = :8080 )'
```

If the daemon/socket is missing, fix host connectivity. Installing a second Docker
inside the agent container does not solve host access. Inspect agent mounts using
a user-selected container name:

```bash
AGENT_CONTAINER=your-agent-container
docker inspect "$AGENT_CONTAINER" --format 'Network={{.HostConfig.NetworkMode}}{{println}}{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}'
```

## Restricted SSH host-command gateway

The writable development checkout is **not** a deployment checkout. The VPS
root operator follows [INSTALLATION.md](../INSTALLATION.md) to clone a reviewed
full commit SHA into a separate root-owned `/srv/signal-desk-releases/<SHA>`
checkout, outside Hermes mounts. Do not re-own the development checkout. The
root-only approval step first independently checks SHA, owner/modes and Hermes
mounts, installs a root-owned verifier copy, then copies the existing
operator-approved `.env` and config (mode 0600) without printing contents. It
pins their hashes, the existing Compose project, and the identity of the volume
mounted by the running API, leaving hostname-only SSH unchanged. The
later, separate one-shot root-terminal activation step installs root-owned scripts,
checks each shell script separately with `bash -n`, validates sudoers and only
then replaces the forced key. Neither step deploys the application.

Prerequisites: VPS root terminal, trusted remote and full reviewed commit SHA,
root-only config staging, existing project/volume, dedicated SSH account with
one hostname-only restricted key, independently trusted public-key fingerprint,
Git, Python 3, Docker/Compose, `sudo`, `visudo` and `ssh-keygen`. The root operator
must inspect the Hermes container's mounts and other host access paths; the
release guard refuses an overlap, writable/replaceable root paths, an altered
commit, code or config, and an unavailable pinned container. Approval requires
`mode: paper` and `execution_enabled: false`. Partial setup needs manual
inspection; no rollback or host acceptance is claimed.

Only **after** root activation, from the agent container with locally configured
host, user, dedicated key and pinned known-hosts path (never in Git):

```bash
SSH_HOST=your-reachable-host-or-gateway
SSH_USER=your-dedicated-ssh-user
SSH_KEY=/path/to/dedicated-private-key
SSH_KNOWN_HOSTS=/path/to/pinned-known-hosts
ssh -T -i "$SSH_KEY" -o IdentitiesOnly=yes -o BatchMode=yes \
  -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$SSH_KNOWN_HOSTS" \
  "$SSH_USER@$SSH_HOST" status
ssh -T -i "$SSH_KEY" -o IdentitiesOnly=yes -o BatchMode=yes \
  -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$SSH_KNOWN_HOSTS" \
  "$SSH_USER@$SSH_HOST" validate
ssh -T -i "$SSH_KEY" -o IdentitiesOnly=yes -o BatchMode=yes \
  -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$SSH_KNOWN_HOSTS" \
  "$SSH_USER@$SSH_HOST" deploy
```

`status` reports the pinned project's state. `validate` checks Compose, builds
and tests the collector. `deploy` invokes guarded paper-only deployment for the
same project and volume. Each request is exactly one operation without flags;
SSH cannot fetch, update or promote a release. The installed verifier checks
protected paths, approved full SHA and config hashes on **every** operation.
Docker-backed operations execute repository code with host/root privileges;
command filtering is not a security sandbox. Local tests do not prove VPS
sshd/sudoers, Docker behavior or clean-host restore.

## Repository and existing settings

```bash
git -c safe.directory="$PWD" remote -v
git -c safe.directory="$PWD" log -1 --oneline
git -c safe.directory="$PWD" status --short
test -f .env || cp .env.example .env
test -f config/config.yaml || cp config/config.example.yaml config/config.yaml
grep -n 'config_version' config/config.yaml config/config.example.yaml config.example.yaml
diff -u config/config.example.yaml config/config.yaml
```

Diff exit=1 means files differ. Do not overwrite active config with an example.
The historical fix for a verified v15/v16 label-only difference was:

```bash
sed -i -e 's/version: v15$/version: v16/' -e 's/config_version: cfg-v15-example-001$/config_version: cfg-v16-example-001/' config/config.yaml
```

This historical correction is not an automatic migration for every installation.

## Build, config, tests and API

```bash
docker compose -p "$PROJECT" config -q
docker compose -p "$PROJECT" build api collector
docker compose -p "$PROJECT" run --rm --no-deps collector python -m signal_desk.tools.validate_all --config config/config.yaml
docker compose -p "$PROJECT" run --rm --no-deps collector python -m pytest -q
docker compose -p "$PROJECT" up -d --no-deps --wait --wait-timeout 90 api
docker compose -p "$PROJECT" ps
docker compose -p "$PROJECT" logs --tail=60 api
curl --fail --show-error http://127.0.0.1:8080/health
docker compose -p "$PROJECT" exec -T api python -m signal_desk.tools.install_check --health-url http://127.0.0.1:8080/health
```

The API may initially show health:starting; up --wait waits for its health check.
ready_for_enter=false is consistent with the incomplete model/ledger scope.

## Snapshot and short stream

```bash
docker compose -p "$PROJECT" run --rm --no-deps collector python -m signal_desk.collector.binance_collector --help
docker compose -p "$PROJECT" run --rm --no-deps collector python -m signal_desk.collector.binance_collector --mode once --config config/config.yaml
docker compose -p "$PROJECT" run --rm --no-deps collector python -u -m signal_desk.collector.binance_collector --mode stream --max-events 25 --config config/config.yaml
echo "STREAM_EXIT_CODE=$?"
docker compose -p "$PROJECT" run --rm --no-deps collector python -u -m signal_desk.collector.binance_collector --mode stream --max-events 1000 --config config/config.yaml
echo "STREAM_EXIT_CODE=$?"
```

Capture output and timeout status in the same shell:

```bash
set -o pipefail
timeout 60s docker compose -p "$PROJECT" run --rm --no-deps collector python -u -m signal_desk.collector.binance_collector --mode stream --max-events 25 --config config/config.yaml 2>&1 | tee /tmp/signal-desk-stream-smoke.log
result=${PIPESTATUS[0]}
echo "STREAM_EXIT_CODE=$result"
```

Exit 124 means timeout. --rm removes the exited container; “No such container” does
not prove success. Read the status file:

```bash
docker compose -p "$PROJECT" run --rm --no-deps collector python -c 'from pathlib import Path; print(Path("/data/status/collector_status.json").read_text())'
```

## Bounded continuous collection, resources and soak

Run only one collector at a time against the same data volume.

```bash
docker compose -p "$PROJECT" run --rm --no-deps collector python -u -m signal_desk.collector.binance_collector --mode continuous --max-run-seconds 60 --config config/config.yaml
echo "CONTINUOUS_EXIT_CODE=$?"
docker compose -p "$PROJECT" run --rm --no-deps collector python -u -m signal_desk.collector.binance_collector --mode continuous --max-run-seconds 300 --config config/config.yaml
echo "CONTINUOUS_EXIT_CODE=$?"
```

Background acceptance test with automatic duration limit:

```bash
TEST_CONTAINER=signal-desk-soak-test
docker compose -p "$PROJECT" run -d --no-deps --name "$TEST_CONTAINER" collector python -u -m signal_desk.collector.binance_collector --mode continuous --max-run-seconds 3600 --config config/config.yaml
docker exec "$TEST_CONTAINER" cat /data/status/collector_status.json
docker stats --no-stream "$TEST_CONTAINER"
docker inspect "$TEST_CONTAINER" --format 'Memory={{.HostConfig.Memory}} NanoCpus={{.HostConfig.NanoCpus}} PidsLimit={{.HostConfig.PidsLimit}}'
docker logs --tail=10 "$TEST_CONTAINER"
docker inspect "$TEST_CONTAINER" --format 'Status={{.State.Status}} ExitCode={{.State.ExitCode}} OOMKilled={{.State.OOMKilled}} StartedAt={{.State.StartedAt}} FinishedAt={{.State.FinishedAt}}'
```

ExitCode=0 while running does not mean the test has completed. Normal completion is
STOPPED, max_run_seconds_reached and exited/0/OOMKilled=false.
session_synchronized=false is expected at shutdown. docker stats is an instantaneous
sample; max_* counters are not p99 measurements.

## Controlled recovery

Only use a dedicated test collector; do not change other services' networks:

```bash
TEST_CONTAINER=your-dedicated-recovery-test
(
set -eu
test_network=$(docker inspect "$TEST_CONTAINER" --format '{{range $name, $config := .NetworkSettings.Networks}}{{println $name}}{{end}}')
[[ -n "$test_network" && "$test_network" != *$'\n'* ]]
trap 'docker network connect "$test_network" "$TEST_CONTAINER" >/dev/null 2>&1 || true' EXIT
docker network disconnect "$test_network" "$TEST_CONTAINER"
sleep 5
docker network connect "$test_network" "$TEST_CONTAINER"
trap - EXIT
)
docker logs --tail=10 "$TEST_CONTAINER"
docker exec "$TEST_CONTAINER" cat /data/status/collector_status.json
```

Expected behavior: retry/backoff, a new session/book, return to RUNNING, then failure
budget reset after stable progress. Do not attribute every timeout to one outage.

## Raw data and scoped audit

After the collector stops:

```bash
docker compose -p "$PROJECT" run --rm --no-deps collector python -c 'from pathlib import Path; files=sorted(Path("/data/raw").glob("*.jsonl")); print("files=",len(files)); [print(f.name, f.stat().st_size) for f in files]'
SESSION_ID=your-completed-session-id
SNAPSHOTS=1
DEPTH_COUNT=your-expected-depth-count
TRADE_COUNT=your-expected-trade-count
docker compose -p "$PROJECT" run --rm --no-deps collector python -u -m signal_desk.tools.audit_raw --raw-dir /data/raw --session-id "$SESSION_ID" --expected-snapshots "$SNAPSHOTS" --expected-depth "$DEPTH_COUNT" --expected-trades "$TRADE_COUNT"
echo "AUDIT_EXIT_CODE=$?"
```

Take expected counts from the corresponding completed run. Files include multiple
trials; total inventory is not the size of one test or a daily volume estimate.
SHA-256 is a local file fingerprint. Passing audit is not replay parity. The old
replay runner loads all JSONL into a list; do not apply it to large files without bounds.

## Version updates and stopping

Only use a reviewed ref/branch:

```bash
git -c safe.directory="$PWD" fetch origin
git -c safe.directory="$PWD" switch main
git -c safe.directory="$PWD" pull --ff-only origin main
git -c safe.directory="$PWD" log -1 --oneline
git -c safe.directory="$PWD" status --short
```

Stop only this Compose project, preserving its volume:

```bash
docker compose -p "$PROJECT" stop
```

Old backup/restore/migration scripts are skeletons; clean-host restore has not passed.
Data deletion, prune, down -v and remove-orphans are not normal installation steps.

## Verified checkpoints (2026-10-27)

- Test stages progressed through 16 → 24 → 49 → 53; the audit candidate passed 67 target-host tests.
- Snapshot, 25/1,000-record, 60/300s and 1h collector runs were validated.
- 1h: 186,898 records, zero gaps/reconnects, exited/0/no OOM.
- Recovery test: two reconnects and return to a fresh healthy session.
- 1h session audit: 1 snapshot + 35,887 depth + 151,010 trades; no errors, exit 0.
- Installer additions have local fake-Docker orchestration tests; 88 local tests passed.
- The existing-VPS installer run returned DEPLOY_OK with paper-only API health.
  Independent clean-server installation remains pending.


## Ordered session replay (new captures only)

See [the replay contract](../references/19-ordered-session-replay.md). Run only in an
operator-reviewed release/development image after collection stops. The installed
SSH gateway does not yet expose a replay operation or select this candidate.
Replace placeholders with a new capture's session ID and recorded counts:

```bash
docker compose -p "$PROJECT" run --rm --no-deps collector \
  python -u -m signal_desk.replay.session \
  --raw-dir /data/raw --session-id "$SESSION_ID" \
  --expected-snapshots "$SNAPSHOTS" --expected-depth "$DEPTH_COUNT" \
  --expected-trades "$TRADE_COUNT"
echo "REPLAY_EXIT_CODE=$?"
```

Require status=ok, expected_counts_checked=true and capture_hashes_verified equal
to all expected records. Repeat the replay and compare feature_sha256. Legacy
sessions without application ordering return unsupported; do not rewrite or sort
the old raw files to force a match. Optional feature output requires a unique path
and an existing parent outside /data/raw; existing files are never overwritten.
