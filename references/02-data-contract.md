# 02 — Data Contract and Schemas

Bu dosya hangi veri tiplerinin kalıcı tutulacağını tanımlar. JSON schema dosyaları `schemas/` altındadır.

## Dosya / tablo aileleri

| Contract | Amaç |
|---|---|
| `market_event` | Binance trade/book/snapshot/delta/heartbeat olayları |
| `feature_snapshot` | O anda bilinen nedensel feature seti |
| `prediction` | Model çıktısı ve model sürümü |
| `decision` | Decision Engine sonucu |
| `order_intent` | Paper emir niyeti ve idempotency anahtarı |
| `paper_fill` | Paper dolum sonucu |
| `eod_report` | Günlük özet ve revision |
| `risk_state` | Günlük risk, açık risk ve latch durumu |
| `model_manifest` | Model artifact ve veri/protokol ilişkisi |
| `run_manifest` | Replay/training/paper run kimliği |

## Değişmez veri ilkeleri

- Raw events append-only tutulur.
- Zamanlar UTC ISO-8601 + exchange timestamp + local receive monotonic delta ile saklanır.
- Aynı fiyattaki farklı olaylar birleştirilmez.
- Duplicate tespiti olay kimliği/sequence/hash ile yapılır.
- Feature snapshot yalnız o anda bilinen veriden üretilir.
- EOD summary eğitim feature'ının yerine geçmez.

## Binance için dikkat

- BTCUSDT ürün türü config’te açık olmalıdır: `spot` veya ileride ayrı deney olarak `futures`.
- V0 varsayılanı spot/paper kavramına göre yazılır; futures fonlama/likidasyon hesabı V0 varsayılanı değildir.
- Tick size, lot size, min notional, fee ve stream türü başlangıçta doğrulanmalıdır.
