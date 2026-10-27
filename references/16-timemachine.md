# Time Machine — separate research feature

## Status and boundaries

2026-10-27: user-accepted feature contract; implementation and results do not exist yet.
Feature name: `timemachine`. Keep it separate from the `replay` module that turns
recorded market events into features. Do not present Time Machine as a prediction
model, new strategy, live order path or paper executor. Preserve Binance BTCUSDT spot
long/flat paper-only scope. Do not make it a prerequisite for VPS smoke tests.

## Reviewed source and adapted method

Source: Jakeschincariol/day-trader-skill, commit
`3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd`, reviewed 2026-10-27.

- [Skill](https://github.com/Jakeschincariol/day-trader-skill/blob/3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd/trader-timemachine/SKILL.md)
- [Code](https://github.com/Jakeschincariol/day-trader-skill/blob/3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd/trader-timemachine/timemachine.py)
- [Tests](https://github.com/Jakeschincariol/day-trader-skill/blob/3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd/tests/test_timemachine.py)
- [MIT license](https://github.com/Jakeschincariol/day-trader-skill/blob/3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd/LICENSE)

The source samples historical-session OHLC/previous-close ratios by time slot,
using 10,000 scenarios and seed=19 by default. It uses stop-first when stop and TP
are touched in the same candle. It reports real historical-rule tests separately.
Historical-rule support is limited to ORB; this is not a backtest of every strategy.
Source tests were inspected, not run here. Source code was not copied or installed.
Preserve the MIT copyright/permission text if code or substantial text is copied later.

## Adaptation decisions

- Do not inherit US session/close/Yahoo assumptions; use validated Binance data and UTC.
  A 60-day history target, 10,000 scenarios and seed=19 are initial research settings,
  not guarantees of sufficient sample size or accuracy.
- Restrict the first bar-based simulation to five-minute bars and at least one full
  bar of horizon. A 60s target requires one-minute data; shorter targets need adequate
  event data. Do not infer 60s outcomes from five-minute OHLC.
- Do not force an exit at a 24-hour boundary. Apply the plan's `horizon_seconds` and
  `time_stop_seconds`; distinguish actual expiry fills from valuation.
- Build pools only from closed bars available before `as_of`. Exclude open bars,
  future corrections, experiment final windows and low-quality/gap intervals.
  Record expected/observed bar counts and available history coverage per window.
- Label independent-bar sampling as `independent_bar_reference_v1`; do not assume
  it preserves serial dependence or volatility clustering. Block bootstrap remains
  a separate candidate. Preregister method, block length and selection range on
  validation before making it the default.
- Do not produce numeric results without fees, slippage, data minimums or a time
  budget. Return `unavailable` with a reason. Freeze minimum coverage in config
  before the experiment; do not claim “20 days is enough” universally or treat
  10,000 sampled paths as independent evidence.
- Use conservative stop-first when stop and target touch in the same bar. If a
  long position gaps below its stop, do not pin exit to the stop: in a bar model,
  apply adverse slippage from min(stop, open). OHLC cannot prove queue order,
  spread or partial fills.
- Net PnL = qty × (exit_fill − entry_fill) − entry_fee − exit_fee.
  Net R = net PnL / initial planned risk; risk = qty × (entry_reference − stop_reference).
  Report fees/slippage as versioned cost assumptions; do not cap loss at −1R.
  Stop/TP probability is not economic edge. Do not hide positions still open at horizon.
- Do not modify live risk, ledger or intents. Run offline or in a separate bounded
  research worker. Never launch on the VPS without explicit CPU/RAM/time limits
  within the total 2 GB profile.

## Two separate outputs

1. `scenario_simulation`: target-first / stop-first / horizon-open fractions on
   synthetic paths; they sum to 1. Report net R and PnL distributions for all paths.
   Do not describe terminal midpoint/bar-price bands as fill or position-return
   bands. Separate Monte Carlo sampling error from market-model uncertainty.
2. `historical_rule_test`: real historical outcomes for a fixed strategy rule and
   causal entries, including trade count, coverage, costs and temporal splits.
   If the L2/trade features required for S1 order-flow are missing, return
   `unsupported`; do not invent results from candles. Do not paste the same scenario
   entry price onto every historical day. Skip this channel with a reason if no
   historical rule is defined for the plan.

Do not combine these channels into one “success probability”; expose disagreement.
Include sample count, date range, seed, algorithm and cost versions in every report.
Select models on validation only; never leak final-test data into simulation pools.

## Planned modules and contracts

Do not describe these as existing or validated files:

- `src/signal_desk/timemachine/`: feature separate from replay.
- `schemas/timemachine_plan.schema.json`, `schemas/timemachine_result.schema.json`.
- Central `timemachine` config: enabled=false, method_version, seed, simulations,
  bar_interval_seconds, horizon_seconds, lookback_days, min_history_bars,
  min_history_days, max_runtime_seconds, max_memory_mb and costs_version.
  Validate parameters with config.schema before connecting them to a runtime mode.
- Plan: plan_id, symbol, product_type, side, as_of, entry_reference, stop_reference,
  target_reference, quantity, horizon/time-stop, strategy/rule_version and costs_version.
- Result: run_id, status/reason, plan/config/data hashes, source commit,
  available_at/as_of, data range/quality, seed/simulations/method, separate
  scenario_simulation and historical_rule_test, resource usage.
- Report: `reports/timemachine/<run_id>.json`; deterministic content for identical
  inputs, method and seed. Exclude runtime fields such as created_at/duration from
  the content hash.

## Acceptance scenarios — required during implementation, not passed yet

- Fixed data/plan/config/seed produce identical results; changed input gets a new fingerprint.
- Adding post-as_of data does not change results; exclude open/gap bars.
- Stop-first; gaps below stops may lose more than −1R; include entry/exit fees and slippage.
- target + stop + open = 1; retain horizon-open PnL and costs in totals.
- Reject a 60s request with five-minute bars.
- Explicit statuses for insufficient data/costs or unsupported historical rules.
- Report method sensitivity separately from real historical results.
- Time/RAM limits actually terminate work without affecting collector/ledger.
- Existing replay outputs and risk/decision tests remain unchanged and pass.

Preserve this contract/source record first; then implement schemas/config, the pure
simulation core, fixture tests, historical-rule adapter and offline reports in order.
