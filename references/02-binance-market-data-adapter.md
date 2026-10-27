# 02 — Binance Market Data Adapter

## Kaynak kararı

V0 yalnız Binance Spot BTCUSDT market data kullanır. Futures/perpetual stream veya filtreleri V0 varsayılanı değildir.

## Kullanılacak streamler

- Depth diff stream: `btcusdt@depth@100ms`.
- Trade stream: `btcusdt@trade` veya aggregation ihtiyacı varsa `btcusdt@aggTrade` ayrı deney olarak.
- Optional book ticker: yalnız latency/health tanısı için; local book yerine geçmez.

## Local order book bootstrap

Binance spot dokümanındaki sıra uygulanır:

1. WebSocket depth stream aç.
2. Gelen depth eventlerini bufferla ve ilk eventin `U` değerini sakla.
3. REST depth snapshot al: `/api/v3/depth?symbol=BTCUSDT&limit=5000`.
4. Snapshot `lastUpdateId` ilk `U` değerinden küçükse snapshotı yeniden al.
5. Buffer içinde `u <= lastUpdateId` olan eventleri at.
6. İlk işlenecek event snapshot `lastUpdateId` değerini `[U, u]` aralığında kapsamalıdır.
7. Snapshot ile book state kur.
8. Buffered ve yeni eventleri sırayla uygula.

## Delta uygulama ve gap kuralı

- `u < local_update_id`: event eski, ignore.
- `U > local_update_id + 1`: gap var; local book discard edilir, resync başlar.
- Normalde bir sonraki eventin `U` değeri önceki `u + 1` olur.
- Price level quantity sıfırsa level silinir; değilse quantity set edilir.
- Snapshot dışındaki seviyeler değişene kadar güvenilir tam miktar olarak kabul edilmez.

## Trade side kuralı

Binance `isBuyerMaker` alanı alıcı tarafın maker olup olmadığını belirtir. Bu nedenle:

- `isBuyerMaker = true`: agresif taraf sell olarak sınıflanır.
- `isBuyerMaker = false`: agresif taraf buy olarak sınıflanır.

Bu alan yoksa trade_side `unknown` olur; model feature’ı bilinmeyen tarafı ayrı ele alır.

## Exchange filters

`/api/v3/exchangeInfo` üzerinden şu filtreler saklanır ve paper intent validasyonunda kullanılır:

- `PRICE_FILTER`.
- `LOT_SIZE`.
- `MARKET_LOT_SIZE`.
- `MIN_NOTIONAL` / `NOTIONAL`.
- `MAX_NUM_ORDERS`.
- `MAX_NUM_ALGO_ORDERS`.
- `TRAILING_DELTA` yalnız future live deneyleri için; V0 paper trailing stop internal simülasyondur.

## Fail-closed davranış

- Snapshot alınamadıysa: collector degraded, ENTER BLOCK.
- Gap/resync sırasında: ENTER BLOCK.
- Trade feed stale: ENTER BLOCK.
- L2 stale: ENTER BLOCK.
- Exchange filters stale: ENTER BLOCK veya stress/default limits ile yeni ENTER yok.

## Gerekli acceptance testleri

- Snapshot/delta bootstrap test.
- Gap detection test.
- Out-of-order/duplicate event test.
- Resync sırasında decision BLOCK test.
- Trade side mapping test.
- Exchange filters parse test.
