# 05 — Resource, Retention and 200 GB Migration

## Başlangıç profili: 100 GB disk / 2 GB RAM

| Alan | Bütçe |
|---|---:|
| Raw Zstd events | 30 GB |
| Feature/label data | 12 GB |
| Prediction/paper/eod logs | 5 GB |
| Models | 2 GB |
| Backups | 5 GB |
| Temp/logs | 6 GB |
| OS/Docker | 15 GB |
| Emergency reserve | 20 GB |
| Spare | 5 GB |

## 200 GB profili

| Alan | 100 GB | 200 GB |
|---|---:|---:|
| Raw Zstd events | 30 GB | 90 GB |
| Feature/labels | 12 GB | 24 GB |
| Prediction/paper/EOD | 5 GB | 10 GB |
| Models | 2 GB | 4 GB |
| Local backups | 5 GB | 15 GB |
| Temp/logs | 6 GB | 10 GB |
| OS/Docker | 15 GB | 20 GB |
| Emergency reserve | 20 GB | 25 GB |
| Spare | 5 GB | 2 GB |

## Migration tetikleyicileri

200 GB’a geçiş öner veya zorunlu hale getir:

- 3 gün üst üste sıkıştırılmış raw veri > 1 GB/gün.
- 60 günlük raw replay isteniyorsa.
- Disk >70% nedeniyle yeni deneyler erteleniyorsa.
- Feature/label pin’leri raw retention’ı 7 gün altına düşürüyorsa.
- Backtest için aynı anda raw + feature + replay temp alanı 100 GB profilini zorluyorsa.

## Disk alarm aksiyonları

| Eşik | Aksiyon |
|---|---|
| >70% | Yeni büyük araştırma başlatma; retention raporu üret |
| >85% | ENTER BLOCK; yeni giriş yok |
| >90% | Maintenance mode; cleanup/backup doğrula |
| >95% | HALT; collector dışında riskli yazıcıları durdur veya read-only moda al |

## RAM kuralları

- Redis başlangıçta yok.
- Toplam live cache en fazla 64 MiB.
- Engine container hedef RSS ≤512 MiB.
- API ≤192 MiB.
- Tek bakım worker ≤384 MiB.
- Ağır eğitim VPS dışında yapılır.
- Docker container memory limits preflight’ta doğrulanır.

## 100 → 200 GB migration runbook

1. HALT gerektirmeyen maintenance window seç.
2. Backup al: config, schemas, SQLite ledger, manifests, model artifacts, latest raw index.
3. Backup hashlerini storage_manifest’e yaz.
4. VPS disk genişlet; filesystem büyütme adımını host sağlayıcıya göre yap.
5. `preflight.sh --profile 200gb_2gb` çalıştır.
6. `config.yaml` resource profile değerini güncelle ve yeni config_version üret.
7. Docker volumes/pathleri değişmeden büyümeyi doğrula.
8. `docker compose up -d --wait`.
9. Raw/feature/model/ledger manifest hash kontrolü.
10. Replay smoke test + EOD idempotency test.
11. Disk alarm thresholdleri yeni profile göre doğrula.
