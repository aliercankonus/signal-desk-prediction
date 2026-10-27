# 10 — EOD Report

EOD raporu insan okunur özet + JSON artefact üretir. Tek günlük rapor model seçimi için tek başına yeterli değildir.

## İçerik

- Veri kapsaması.
- Gap/stale/reconnect sayısı.
- Disk/RAM/cache durumu.
- Sinyal sayısı: produced, blocked, entered, exited.
- Strateji bazlı brüt/net sonuç.
- Fee/slippage etkisi.
- Paper-fill mode kırılımı.
- Markout özeti.
- Model accuracy/calibration metrics.
- Risk: max drawdown, daily loss latch, stops.
- Alarm özeti.
- Araştırma önerileri.

## Revision ve idempotency

- Aynı gün için rapor tekrar üretilebilir.
- Geç gelen/reconciled fill varsa `revision` artar.
- Önceki revision overwrite edilmez.
- Final-test sonuçları model seçimine sızdırılmaz.

## Gün kesimi

Config timezone: Europe/Amsterdam veya UTC olarak tanımlanır. V0 önerisi UTC trading day’dir; kullanıcı raporu Amsterdam yerel saatini de gösterebilir.

## Örnek JSON alanları

`eod_report.schema.json` zorunlu alanları: summary, data_quality, strategy_results, model_results, paper_results, alarms, revisions.
