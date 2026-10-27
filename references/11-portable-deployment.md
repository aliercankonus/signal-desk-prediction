# 11 — Portable Deployment

## Hedef

Başka desteklenen Linux sunucusunda:

```bash
cp .env.example .env
# config doldur
docker compose config -q
docker compose up -d --wait
```

ile sistem veri sıfırlamadan başlamalıdır.

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

## Bootstrap modları

1. **Fresh start:** Model yoksa prediction unavailable; collector veri toplamaya başlar.
2. **Restore start:** Backup + model bundle + manifests doğrulanır; sonra readiness.

## Readiness kapıları

- Config valid.
- Disk/RAM profile valid.
- Schema migrations applied.
- Volumes writable.
- Binance market data connected or explicitly unavailable.
- Ledger writable.
- Model loaded or unavailable marked.
- Paper mode confirmed.
- No live execution.

## Clean-host kabul

- Elle kod düzenlemesi yok.
- Eski `/opt` yollarına bağımlılık yok.
- Container names namespace içinde.
- Restart sonrası checkpoint korunur.
- Backup restore hashleri tutar.
