# 03 — Data Contract and Schemas

JSON schemas are in `schemas/`. All persistent events must pass schema validation.

## Contracts

| Contract | Purpose |
| --- | --- |
| `market_event` | Binance trade/book/snapshot/delta/heartbeat/status events |
| `feature_snapshot` | Causal features known at that time |
| `prediction` | Model output and version |
| `decision` | Decision Engine result and telemetry |
| `order_intent` | Paper order intent and idempotency key |
| `paper_fill` | Paper fill/partial-fill result |
| `ledger_entry` | Append-only paper ledger |
| `risk_state` | Daily risk, open risk and latch state |
| `eod_report` | Daily summary and revision |
| `model_manifest` | Model artifact and data/protocol relationship |
| `run_manifest` | Replay/training/paper run identity |
| `alarm_event` | Alarm, severity, action and resolution |
| `storage_manifest` | File set, hash and retention pin |
| `config` | Central runtime configuration contract |

## Immutable data principles

- Raw events are append-only.
- Store UTC ISO-8601 time, exchange timestamp, local receive timestamp and monotonic ns.
- Preserve different events at the same price; deduplicate only true duplicates by event ID/hash.
- Replay and live processing use the same feature code path.
- Feature snapshots cannot use future data.
- Paper fills must not be presented as real fills; mode and assumptions are required.

## Time contract

- `exchange_ts`: Binance event time.
- `received_ts`: collector wall-clock UTC.
- `monotonic_ns`: process monotonic time.
- `asof_ts`: latest valid time known for a decision/prediction.
- `valid_until`: signal/decision validity deadline.
- `expires_at`: intent or paper-order waiting deadline.

## Decimal rule

Store prices and quantities as decimal strings in JSON. Use Decimal or integer
ticks/lots internally; do not persist binary floating-point prices or quantities.
