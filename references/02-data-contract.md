# 02 — Data Contract and Schemas

JSON schemas are in `schemas/`. This file defines which data types are persisted.

## Contracts

| Contract | Purpose |
| --- | --- |
| `market_event` | Binance trade/book/snapshot/delta/heartbeat events |
| `feature_snapshot` | Causal features known at that time |
| `prediction` | Model output and version |
| `decision` | Decision Engine result |
| `order_intent` | Paper order intent and idempotency key |
| `paper_fill` | Paper fill result |
| `risk_state` | Daily risk, open risk and latch state |
| `eod_report` | Daily summary and revision |
| `model_manifest` | Model artifact and data/protocol relationship |
| `run_manifest` | Replay/training/paper run identity |

## Immutable data principles

- Raw events are append-only.
- Store UTC ISO-8601 time, exchange timestamp and local receive monotonic delta.
- Do not merge different events at the same price.
- Detect duplicates by event identity/sequence/hash.
- Generate feature snapshots only from data known at that time.
- EOD summaries do not replace training features.

## Binance considerations

- Specify BTCUSDT product type in config: `spot`, or `futures` in a separate future experiment.
- V0 defaults describe spot/paper behavior; futures funding/liquidation calculations are not V0 defaults.
- Verify tick size, lot size, minimum notional, fees and stream type at startup.
