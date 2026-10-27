# 12 — Portable Deployment

## Hedef

Desteklenen temiz Linux sunucusunda:

```bash
cp .env.example .env
# config doldur
docker compose config -q
docker compose up -d --wait
```

ile sistem veri sıfırlamadan başlayabilmelidir.

## Gerekli implementation skeleton

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

## Servisler

- `collector`
- `feature-engine`
- `prediction`
- `decision-engine`
- `paper-executor`
- `api`
- `eod-worker`
- `maintenance`

## Kalıcı alanlar

- `/data/raw`
- `/data/features`
- `/data/ledger`
- `/data/models`
- `/data/reports`
- `/data/backups`
- `/data/manifests`

## Bootstrap modları

1. Fresh start: model yoksa prediction unavailable; collector veri toplamaya başlar.
2. Restore start: backup + model bundle + manifests doğrulanır.
3. Replay-only: canlı stream olmadan fixture/raw replay ile test.

## Readiness kapıları

- Config valid.
- Disk/RAM profile valid.
- Docker memory/resource limits detectable.
- Schema migrations applied.
- Volumes writable.
- Binance market data connected or explicitly unavailable.
- Ledger writable.
- Model loaded or unavailable marked.
- Paper mode confirmed.
- No live execution.

## Docker resource policy

Compose resource limits veya engine-level memory limits preflight ile doğrulanır. Limit tanımı yapıldı diye hostta uygulandığı varsayılmaz; `docker stats`/inspect kontrolü gerekir.

## Clean-host kabul

- Elle kod düzenlemesi yok.
- Eski `/opt` yollarına bağımlılık yok.
- Container names namespace içinde.
- Restart sonrası checkpoint korunur.
- Backup restore hashleri tutar.
