# Decision: V0 Binance BTCUSDT Spot Paper-Only

## Status
accepted

## Context
V0 kapsamını belirsiz exchange/sembol kararından çıkarmak ve implementation/test odağını daraltmak.

## Sources checked
- Binance Spot WebSocket docs: depth stream and local order book process.
- Binance Spot filters docs: LOT_SIZE, MIN_NOTIONAL/NOTIONAL, MARKET_LOT_SIZE.
- Docker docs: memory/resource limits.

## Decision
V0 Binance BTCUSDT spot paper-only olarak sabitlendi.

## Alternatives
- Coinbase: önceki aday, V0’da kullanılmayacak.
- Futures/perpetual: V1+ deney.

## Risks
Binance API erişimi/terms/latency Avrupa’dan beklenenden kötü olabilir; adapter değiştirilebilir tutulmalı.

## Tests added
- Binance snapshot/delta bootstrap.
- Gap resync.
- Trade side mapping.
- Exchange filter parsing.

## Rollback
Exchange adapter interface korunur; yeni exchange adapter V1 olarak eklenebilir.
