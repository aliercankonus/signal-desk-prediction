# Decision: V0 Binance BTCUSDT Spot Paper-Only

## Status
accepted

## Context

Resolve the exchange/symbol choice and narrow implementation/testing scope for V0.

## Sources checked

- Binance Spot WebSocket docs: depth stream and local order book process.
- Binance Spot filters docs: LOT_SIZE, MIN_NOTIONAL/NOTIONAL, MARKET_LOT_SIZE.
- Docker docs: memory/resource limits.

## Decision

Fix V0 to Binance BTCUSDT spot paper-only.

## Alternatives

- Coinbase: an earlier candidate, not selected for V0.
- Futures/perpetual: V1+ experiment.

## Risks

Binance API access, terms or latency from Europe may be worse than expected; keep
the adapter replaceable.

## Tests added

- Binance snapshot/delta bootstrap.
- Gap resync.
- Trade-side mapping.
- Exchange-filter parsing.

## Rollback

Preserve the exchange adapter interface; add a different exchange adapter as V1.
