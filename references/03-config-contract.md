# 03 — Central Config Contract

Read all settings centrally from `config.yaml`. Do not hide defaults in code.

## Required config fields

```yaml
project:
  name: signal-desk-prediction
  version: v12
  mode: paper
  execution_enabled: false

exchange:
  name: binance
  product_type: spot
  symbol: BTCUSDT
  quote_asset: USDT
  market_data:
    book_depth: 20
    trades_stream: true
    book_stream: true
    heartbeat_timeout_ms: 3000
    stale_l2_ms: 2000
    stale_trades_ms: 3000

resources:
  profile: 100gb_2gb
  disk_total_gb: 100
  ram_total_mb: 2048
  cache_total_mib: 64

retention:
  raw_target_days: 7
  raw_pool_gb: 30
  feature_days: 30
  feature_pool_gb: 12
  minute_aggregate_days: 180
  prediction_days: 30
  eod_days: 365

risk:
  starting_equity_usdt: 10000
  risk_per_trade_pct: 0.25
  daily_loss_limit_pct: 1.0
  max_position_notional_pct: 10
  max_open_positions: 1
  reentry_cooldown_seconds: 60
  after_stop_cooldown_seconds: 300

paper_fill:
  mode: conservative
  fee_bps_taker: null
  fee_bps_maker: null
  slippage_model: conservative_spread_based
  same_interval_stop_target_ordering: stop_first

strategy:
  enabled: [S0, S1]
  primary: S1
  horizons_seconds: [60, 300]
  decision_frequency_hz: 1

alarms:
  disk_enter_block_pct: 85
  disk_halt_pct: 95
  ram_warn_pct: 80
  ram_halt_pct: 95
```

## Config versioning

- Every change creates a `config_version`.
- Record risk-parameter changes in the manifest, even in paper mode.
- If stop/risk config changes with an open position, record the effect on that position separately.
- Increasing the daily loss limit requires manual approval; decreases may apply immediately.
