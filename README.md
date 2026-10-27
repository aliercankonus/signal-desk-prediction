# signal-desk-prediction v16

Sıfırdan kurulacak, taşınabilir, Binance BTCUSDT spot paper-only kısa vadeli tahmin, replay, EOD ve karar sistemi paketi.

Bu paket canlı trading yazılımı değildir. Gerçek emir üretmez; amaç G0-G2/G3 hazırlığını çalışan kod iskeletiyle ilerletmektir.

## v16 değişiklikleri

- v14 runnable skeleton üzerine replay runner eklendi.
- Basit causal feature engine eklendi: L2 top-of-book + trade delta feature snapshot üretir.
- Storage manifest üretici eklendi; runtime dosyalarını hash ve byte bilgisiyle listeler.
- EOD skeleton eklendi; raw/features/ledger sayımlarını idempotent JSON rapora döker.
- Alarm manager eklendi; disk/RAM/stale/ledger hatalarını INFO/WARN/BLOCK/HALT aksiyonlarına çevirir.
- Binance L2 gap detection testleri genişletildi.
- Test suite 16 teste çıkarıldı.

## Ana dosyalar

- `SKILL.md`: kısa kullanım rehberi.
- `references/`: ayrıntılı teknik sözleşmeler.
- `schemas/`: JSON schema sözleşmeleri.
- `config/config.example.yaml`: örnek config.
- `src/signal_desk/`: çalışan Python skeleton.
- `tests/`: otomatik testler.
- `PROJECT_STATE.md`: mevcut hazırlık durumu.
- `CHANGELOG.md`: değişiklik kayıtları.

## Quick start

```bash
cp .env.example .env
cp config/config.example.yaml config/config.yaml
PYTHONPATH=src ./scripts/bootstrap.sh
PYTHONPATH=src ./scripts/preflight.sh
PYTHONPATH=src python -m pytest -q
```

## Replay / EOD örnekleri

```bash
PYTHONPATH=src python -m signal_desk.replay.runner --input runtime/data/raw/example.jsonl --output runtime/data/features/example.features.jsonl --config config/config.yaml
PYTHONPATH=src python -m signal_desk.eod.report --config config/config.yaml --date 2026-10-26
PYTHONPATH=src python -m signal_desk.storage.manifest --config config/config.yaml --output runtime/data/status/storage_manifest.json
```

Optional local health API without Docker:

```bash
PYTHONPATH=src python -m signal_desk.api.health_server --host 127.0.0.1 --port 8080
PYTHONPATH=src ./scripts/healthcheck.sh http://127.0.0.1:8080/health
```

Optional Binance REST snapshot smoke test. This writes one validated market event to the configured raw path and does not place orders:

```bash
PYTHONPATH=src python -m signal_desk.collector.binance_collector --mode once --config config/config.yaml
```

Docker commands to run on a host with Docker installed:

```bash
docker compose config -q
docker compose build
docker compose up -d --wait
./scripts/healthcheck.sh http://127.0.0.1:8080/health
```

The skeleton is paper-only. Real execution remains disabled and out of scope.
