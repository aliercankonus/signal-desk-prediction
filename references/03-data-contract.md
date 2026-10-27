# 03 — Data Contract and Schemas

JSON schema dosyaları `schemas/` altındadır. Tüm kalıcı eventler schema validation’dan geçmelidir.

## Sözleşmeler

| Contract | Amaç |
|---|---|
| `market_event` | Binance trade/book/snapshot/delta/heartbeat/status olayları |
| `feature_snapshot` | O anda bilinen nedensel feature seti |
| `prediction` | Model çıktısı ve model sürümü |
| `decision` | Decision Engine sonucu ve telemetry |
| `order_intent` | Paper emir niyeti ve idempotency anahtarı |
| `paper_fill` | Paper dolum/kısmi dolum sonucu |
| `ledger_entry` | Append-only paper ledger |
| `risk_state` | Günlük risk, açık risk, latch durumu |
| `eod_report` | Günlük özet ve revision |
| `model_manifest` | Model artifact ve veri/protokol ilişkisi |
| `run_manifest` | Replay/training/paper run kimliği |
| `alarm_event` | Alarm, severity, action, resolution |
| `storage_manifest` | Dosya seti, hash, retention pin |
| `config` | Merkezi runtime config sözleşmesi |

## Değişmez veri ilkeleri

- Raw events append-only tutulur.
- Zamanlar UTC ISO-8601 + exchange timestamp + local receive timestamp + monotonic ns ile saklanır.
- Aynı fiyattaki farklı olaylar korunur; yalnız gerçek duplicate event id/hash ile deduplicate edilir.
- Replay/live aynı feature kod yolunu kullanır.
- Feature snapshot gelecekteki veri kullanamaz.
- Paper fill gerçek fill gibi sunulmaz; mode ve assumption zorunludur.

## Zaman sözleşmesi

- `exchange_ts`: Binance event time.
- `received_ts`: collector wall-clock UTC.
- `monotonic_ns`: process monotonic time.
- `asof_ts`: karar/tahmin için bilinen son geçerli zaman.
- `valid_until`: sinyal/kararın geçerlilik bitişi.
- `expires_at`: intent veya paper order bekleme bitişi.

## Decimal kuralı

Fiyat ve miktarlar JSON’da string decimal olarak saklanır. Internal hesapta Decimal/tick/lot integer kullanılır; binary float kalıcı kayıtta kullanılmaz.
