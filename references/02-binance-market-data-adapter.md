# 02 — Binance Market Data Adapter

## Source decision

V0 uses only Binance Spot BTCUSDT market data. Futures/perpetual streams or filters
are not V0 defaults.

## Streams

- Depth diff stream: `btcusdt@depth@100ms`.
- Trade stream: `btcusdt@trade`; evaluate `btcusdt@aggTrade` separately if aggregation is needed.
- Optional book ticker: latency/health diagnostics only; not a replacement for the local book.

## Local order book bootstrap

Follow the sequence in the Binance Spot documentation:

1. Open the WebSocket depth stream.
2. Buffer incoming depth events and retain the first event's `U`.
3. Fetch the REST depth snapshot: `/api/v3/depth?symbol=BTCUSDT&limit=5000`.
4. Fetch again if snapshot `lastUpdateId` is smaller than the first `U`.
5. Discard buffered events with `u <= lastUpdateId`.
6. The first event to apply must cover snapshot `lastUpdateId` in its `[U, u]` range.
7. Initialize book state from the snapshot.
8. Apply buffered and new events in order.

## Delta application and gap rules

- `u < local_update_id`: stale event; ignore it.
- `U > local_update_id + 1`: gap; discard the local book and start resync.
- Normally the next event's `U` equals the previous `u + 1`.
- Delete a price level when quantity is zero; otherwise set its quantity.
- Levels outside the snapshot are not considered reliable complete quantities until updated.

## Trade-side rule

Binance `isBuyerMaker` indicates whether the buyer is the maker:

- `isBuyerMaker = true`: classify the aggressor as sell.
- `isBuyerMaker = false`: classify the aggressor as buy.

If missing, trade_side is `unknown`; model features must handle unknown sides separately.

## Exchange filters

Persist the following from `/api/v3/exchangeInfo` and use them to validate paper intents:

- `PRICE_FILTER`.
- `LOT_SIZE`.
- `MARKET_LOT_SIZE`.
- `MIN_NOTIONAL` / `NOTIONAL`.
- `MAX_NUM_ORDERS`.
- `MAX_NUM_ALGO_ORDERS`.
- `TRAILING_DELTA` only for future live experiments; V0 paper trailing stops are internal simulations.

## Fail-closed behavior

- Snapshot unavailable: collector degraded; ENTER BLOCK.
- Gap/resync in progress: ENTER BLOCK.
- Trade feed stale: ENTER BLOCK.
- L2 stale: ENTER BLOCK.
- Exchange filters stale: ENTER BLOCK, or stress/default limits with no new ENTER.

## Required acceptance tests

- Snapshot/delta bootstrap.
- Gap detection.
- Out-of-order/duplicate events.
- Decision BLOCK during resync.
- Trade-side mapping.
- Exchange-filter parsing.
