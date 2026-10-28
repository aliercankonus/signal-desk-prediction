# Decision: fixed causal baselines and a provisional S1 flow diagnostic

## Status
Proposed for review, 2026-10-28. No strategy run, calibration, parameter search,
selection, fill simulation or economic acceptance has been performed.

## Context
`CausalFeaturePipeline` already provides a verified application-order transition,
book bridge, freshness and capture-time feature digest. `FeatureState` exposes
best bid/ask/size, midpoint and top-book imbalance. Its misleadingly named
`buy_qty_window`, `sell_qty_window` and `trade_delta_qty_window` are **lifetime
since session reset**, not time-windowed quantities. Top-book imbalance is a
**standing depth snapshot**, not observed order flow. Neither may silently
stand in for 30-second aggressive trade flow. Old raw data without the
application-order metadata cannot recover causality by sorting timestamps.

## Sources checked
- Binance Spot trade stream specifies the buyer-maker flag `m`; a maker buyer
  implies sell aggressor for a trade. Its diff-depth documentation requires a
  synchronized local book and restart on missed update IDs. [1]
- Cont, Kukanov and Stoikov study **order-book-event flow imbalance** and its
  association with price changes. That measure is not our aggressive-trade
  volume ratio, and the paper does not validate BTCUSDT 60/300-second results. [2]
- Stoikov distinguishes a fitted micro-price from the simple weighted
  midpoint. Our fixed weighted-midpoint proxy must not be described as his
  calibrated estimator or as a forecast of a 1/5-minute return. [6]
- scikit-learn's `TimeSeriesSplit` documents chronological train/test order and
  a sample-count gap; our proposed **seconds-based** label purge and embargo
  are an explicit project choice, not a claim that its class implements them. [4]

## Decision
Predeclare `docs/research/s1_experiment_v1.json` before using results. In an
offline-only runner, use `SessionInput` to merge by application sequence and
`CausalFeaturePipeline` to validate every stored capture feature hash. Every
candidate gets identical UTC 30-second prediction instants and fixed
freshness, spread, synchronization and warm-up gates for separate 60/300-second
midpoint-direction labels, independent of the recorded capture policy used
only to verify feature hashes. The last applied label quote must be no later
than `due_at` and pass the fixed bridge/depth/trade freshness/spread gates;
a later invalid quote cannot be replaced by an earlier one. A missing or
invalid due-time quote is invalid, while a session ending before `due_at` is
pending. Preserve invalid/no-output rows. No probability, return estimate,
fees, execution intent or PnL is emitted.

The first research-only flow overlay maintains signed BTC quantity for **actual
trade events** with application cutoff in the inclusive interval
`[prediction_at - 30s, prediction_at]`. Buy-aggressor quantity is positive and
sell-aggressor quantity negative; at least two trades and positive total
absolute quantity are required. The ratio is `(buy - sell)/(buy + sell)`.
At a prediction time the weighted-midpoint proxy is
`(ask * bid_qty + bid * ask_qty)/(bid_qty + ask_qty)` using the current best
levels. Its reference score is `(proxy - midpoint)/spread`. The provisional S1
raw score is `0.7 * trade_ratio + 0.3 * proxy_score`; the weights are fixed
pre-results and **not optimized or probabilistic**. The no-change score is
zero. Momentum is the 60-second causal midpoint change divided by the older
midpoint. Select the latest applied state at or before the lookback cutoff,
including wide-spread or missing-book transitions; never fall back to an
earlier valid quote. The selected state must pass the fixed depth, trade and
spread gates again at the lookback instant. These unitless/raw
scores are diagnostics, not comparable calibrated return predictions.

A future shared live feature pipeline needs a **new version** with explicit
`aggressive_buy_qty_30s`, `aggressive_sell_qty_30s`,
`aggressive_trade_count_30s`, `flow_window_start_applied_ts` and a
`flow_ready_30s` flag. Include only ordered trades whose local application
cutoff lies in the inclusive 30-second interval, remove older trades on each
transition, reset on a new session/reconnect, cap retained trades, and mark
not-ready for missing trade freshness, bridge, gap, insufficient trades or
window-cap exhaustion. This PR computes the overlay in offline research only;
it **does not** change the capture feature version or claim live parity for it.

## Alternatives
Do not treat standing top-book imbalance, lifetime counters, venue-time sorted
legacy files, or a weighted midpoint as a true rolling trade-flow feature or a
trained Stoikov micro-price. Do not train logistic/CatBoost or tune thresholds
on a short local fixture. Do not infer fees from exchange marketing pages.

## Risks
A 30-second signed-volume ratio ignores order submissions/cancellations and
is not the paper's full order-flow imbalance. Application time can lag exchange
time; stale/gap checks and coverage diagnostics expose but do not remove every
bias. Fixed weights may be poor. Test-window leakage is possible unless each
label is purged from the next split and the final window is used only once.
The current runner is bounded per completed session; the proposed 60-day
split and any economic assessment require separate, reviewed data and the
shared conservative paper-fill/risk/ledger core.

## Tests added
Real mapped capture fixtures check application-order hashes, common grid,
future-prefix invariance, warm-up, stale/wide due-at quote rejection, exact 300s
due boundary, pending/no-output retention, legacy/gap rejection, output
no-overwrite/atomicity, bounded metadata/input checks, stricter capture-policy
parity and deterministic reruns. No VPS load is induced.

## Rollback
Revert this proposed research module/spec/tests and keep existing capture,
replay, paper-only API, data volume and Time Machine unchanged.

## Sources

[1] https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md
[2] https://arxiv.org/abs/1011.6402
[4] https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html
[6] https://papers.ssrn.com/sol3/Delivery.cfm/SSRN_ID3165260_code1121907.pdf?abstractid=2970694&mirid=1&type=2 — Stoikov, The Micro-Price
