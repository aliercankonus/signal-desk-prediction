# 04 — Resource, Retention and 200 GB Migration

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

200 GB’a geçilirse amaç 60 günlük raw replay’i daha rahat desteklemek ve araştırma pencerelerini silme baskısı olmadan yürütmektir.

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

200 GB’a geçiş öner:

- 3 gün üst üste sıkıştırılmış raw veri > 1 GB/gün.
- 60 günlük raw replay isteniyorsa.
- Disk %70 üstünde yeni deneyler erteleniyorsa.
- Feature/label pin’leri raw retention’ı 7 gün altına düşürüyorsa.

## Disk aksiyonları

| Eşik | Aksiyon |
|---|---|
| >70% | Yeni büyük araştırma başlatma; retention raporu üret |
| >85% | ENTER BLOCK; yeni giriş yok |
| >90% | Maintenance mode; cleanup/backup doğrula |
| >95% | HALT; collector hariç riskli yazıcıları durdur veya read-only moda al |

## RAM kuralları

- Redis başlangıçta yok.
- Toplam live cache en fazla 64 MiB.
- Engine container hedef RSS ≤512 MiB.
- API ≤192 MiB.
- Tek bakım worker ≤384 MiB.
- Ağır eğitim VPS dışında yapılır.

## Migration kabulü

1. Yedek alınır.
2. Yeni disk alanı doğrulanır.
3. Docker volumes ve paths değişmeden büyür veya restore edilir.
4. `docker compose up -d --wait`.
5. Raw/feature/model manifest hash kontrolü.
6. EOD ve paper ledger idempotency kontrolü.
