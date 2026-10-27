# 12 — Portable Deployment

## Target

On another supported clean Linux server, the system should start without resetting data:

```bash
cp .env.example .env
# Populate config
docker compose config -q
docker compose up -d --wait
```

## Required implementation skeleton

```text
signal-desk-prediction/
  docker-compose.yml
  .env.example
  config/config.example.yaml
  config/config.schema.json
  schemas/
  src/collector/
  src/storage/
  src/features/
  src/prediction/
  src/strategy/
  src/risk/
  src/decision/
  src/paper/
  src/eod/
  src/api/
  tests/schema/
  tests/config/
  tests/replay/
  tests/decision/
  tests/paper_fill/
  tests/deployment/
  fixtures/binance_sample_events/
  scripts/bootstrap.sh
  scripts/preflight.sh
  scripts/backup.sh
  scripts/restore.sh
  scripts/migrate-200gb.sh
  PROJECT_STATE.md
  CHANGELOG.md
```

## Services

- `collector`
- `feature-engine`
- `prediction`
- `decision-engine`
- `paper-executor`
- `api`
- `eod-worker`
- `maintenance`

## Persistent paths

- `/data/raw`
- `/data/features`
- `/data/ledger`
- `/data/models`
- `/data/reports`
- `/data/backups`
- `/data/manifests`

## Bootstrap modes

1. Fresh start: prediction is unavailable without a model; the collector starts gathering data.
2. Restore start: validate backup, model bundle and manifests.
3. Replay-only: test fixtures/raw replay without a live stream.

## Readiness gates

- Config valid.
- Disk/RAM profile valid.
- Docker memory/resource limits detectable.
- Schema migrations applied.
- Volumes writable.
- Binance market data connected or explicitly unavailable.
- Ledger writable.
- Model loaded or marked unavailable.
- Paper mode confirmed.
- No live execution.

## Docker resource policy

Verify Compose or engine-level resource/memory limits during preflight. Declaring
limits does not prove host enforcement; check `docker stats` and inspect output.

## Clean-host acceptance

- No manual code editing.
- No dependency on old `/opt` paths.
- Container names stay within the namespace.
- Checkpoints survive restart.
- Backup/restore hashes match.
