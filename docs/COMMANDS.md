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

This is separate from application installation. Review the checkout and
[INSTALLATION.md](../INSTALLATION.md) before changing host authorization.
Prerequisites on the VPS: a root terminal; an existing checkout with `.env` and
`config/config.yaml`; the existing Compose project name from `.env`; a dedicated
SSH account with **exactly one** active ed25519 authorized key; `sudo`, `visudo`,
`ssh-keygen`, `runuser`, Git and a working host Docker/Compose installation. Confirm the
active config remains `mode: paper` and `execution_enabled: false`. Obtain the
expected SSH-key fingerprint from a trusted copy of the public key, not solely
from the host's mutable `authorized_keys` file. The current hostname-only key
cannot install this gateway remotely.

From the existing checkout in the **VPS root terminal**, set host-local values
and run the one-time installer. Do not commit host identities, key material or
private settings:

```bash
REPO="$PWD"
AGENT_USER=your-dedicated-ssh-user
KEY_COMMENT=your-public-key-comment
KEY_FINGERPRINT=SHA256:your-independently-verified-key-fingerprint
PROJECT=your-existing-COMPOSE_PROJECT_NAME
EXPECTED_HOST=$(hostname)
bash scripts/install-host-gateway.sh --repo "$REPO" \
  --agent-user "$AGENT_USER" --key-comment "$KEY_COMMENT" \
  --key-fingerprint "$KEY_FINGERPRINT" --project "$PROJECT" \
  --expected-host "$EXPECTED_HOST"
```

The script refuses a host/project mismatch, multiple active authorized keys,
a key fingerprint mismatch, unexpected existing key options (including extra
`from=` restrictions), missing config or unsafe paper/execution settings. It
also refuses source/config/Git paths or home ancestors writable by the agent.
It copies the dispatcher and gateway into root-owned host paths, writes a
root-owned configuration, validates an exact three-command sudoers file with
`visudo`, makes the dedicated account's home and SSH files root-owned, then
atomically replaces the authorized key with a `restrict,command=...` entry.
Only after the forced key is in place does it publish sudoers privileges.
Review ownership and existing account files first. If an intermediate step
fails, inspect the host's partial state; do not assume automatic rollback.
No application deployment occurs during this one-time setup.

From the agent container, use locally configured host, user, key and pinned
known-hosts paths (none belong in Git):

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

`status` reports the existing Compose project's state. `validate` checks
Compose, builds the collector image from reviewed source, then runs application
validation and pytest in disposable containers; `deploy`
invokes the existing guarded deployment script, which builds, runs bounded
smoke tests and starts only the API. Run `status` first; only run the others
after reviewing and committing the exact source revision. Extra words, flags,
newlines and arbitrary commands are rejected. `validate` and `deploy` refuse
tracked code changes (except active config) and untracked repository files.
Neither command enables continuous collection, live execution or a new volume.

**Limitations:** a forced SSH command and exact sudoers entries do not sandbox
repository code. Docker-backed validation/deployment execute repository inputs
with host/root privileges. The agent must not own or write the host checkout,
root-owned gateway files or active key authorization. Review existing sshd
policy and sudo rights independently; this installer does not revoke them.
Local mocked checks cannot prove VPS sudoers, sshd, Docker or clean-host restore.

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
