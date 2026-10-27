# 04 — Config Contract

Manage all runtime decisions through central `config.yaml`, validated against
`schemas/config.schema.json`.

## Required config sections

- `project`: name, version, mode, execution flag, config_version.
- `exchange`: Binance spot BTCUSDT endpoints, stream names, stale limits.
- `fees`: maker/taker bps, source, last_verified_ts, stale policy.
- `filters`: Binance exchangeInfo-derived symbol filters.
- `resources`: 100gb_2gb or 200gb_2gb profile.
- `storage`: raw/features/ledger/models/reports/backups paths and codecs.
- `retention`: TTL days, pool GB and pin policies.
- `cache`: RAM budgets and ring-buffer sizes.
- `risk`: trade risk, daily loss, notional, cooldowns.
- `decision`: frequency, stale gates, idempotency settings.
- `paper_fill`: mode and assumptions.
- `strategies`: enabled strategy IDs and sequence.
- `models`: active model/baseline IDs.
- `alarms`: thresholds and actions.
- `eod`: timezone, cutoff, revision behavior.

## Config version policy

- Every risk/fee/fill/strategy/model change creates a new `config_version`.
- With an open position, retain its old config; use the new config for new entries.
- Apply a lower daily loss limit immediately.
- Increasing the daily loss limit requires a manual approval record.

## Fee policy

- Missing maker/taker fees: ENTER BLOCK.
- Stale fees: ENTER BLOCK, or analysis-only mode with an explicitly defined stress fee.
- Record fee source and timestamp in paper results.

## Config startup gates

- `config.schema.json` valid.
- `execution_enabled=false`.
- `mode=paper`.
- `exchange.product_type=spot`.
- `exchange.symbol=BTCUSDT`.
- Fee fields non-null for paper trading.
- Storage paths writable.
- Resource profile consistent with host preflight.
