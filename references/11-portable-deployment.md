# 11 — Portable Deployment

## Target

On another supported Linux server, the system should start without resetting data:

```bash
cp .env.example .env
# Populate config
docker compose config -q
docker compose up -d --wait
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

## Bootstrap modes

1. Fresh start: prediction is unavailable without a model; the collector starts gathering data.
2. Restore start: validate backup, model bundle and manifests before readiness.

## Readiness gates

- Config valid.
- Disk/RAM profile valid.
- Schema migrations applied.
- Volumes writable.
- Binance market data connected or explicitly unavailable.
- Ledger writable.
- Model loaded or marked unavailable.
- Paper mode confirmed.
- No live execution.

## Clean-host acceptance

- No manual code editing.
- No dependency on old `/opt` paths.
- Container names stay within the namespace.
- Checkpoints survive restart.
- Backup/restore hashes match.
