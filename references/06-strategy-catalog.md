# 06 — Strategy Catalog

## Category sequence

| Category | Strategy | Purpose | Activation |
| --- | --- | --- | --- |
| Baseline | S0 no-trade / midpoint / momentum | Reference | Required in V0 |
| Primary | S1 order-flow continuation | First trading hypothesis | V0 primary |
| Variant | S1b cost gate | S1 cost filter | After S1 |
| Variant | S1c fixed stop/TP/time stop | Risk-controlled S1 | After S1b |
| Variant | S1d trailing stop A/B | Position-management test | After S1c |
| Secondary | S2 breakout/retest | Momentum/breakout hypothesis | V1 |
| Secondary | S3 VWAP mean reversion | Sideways-market reversion hypothesis | V1 |

## V0 rule

V0 includes interfaces for all strategies; active paper decisions start with S0 + S1.
S2/S3 may be implemented but must not produce ENTER by default; they can run in
replay/analysis mode.

## Position management

- Do not repeatedly close/reopen merely because the upward expectation persists.
- Preserve HOLD as the default for an existing position.
- Updating protection is separate from closing: UPDATE_STOP.
- A long stop only moves upward, never downward.
- A new prediction does not reset maximum holding duration.
- Re-entry requires confirmed closure, cooldown and a new signal.

## S1 order-flow continuation

Candidate inputs:

- Trade aggressor imbalance.
- Order book imbalance.
- Micro-price / weighted midpoint divergence.
- Spread and depth.
- Event intensity.
- Short-window returns.

Decision:

- Signal valid_until is required.
- Expected move > fee + spread + slippage stress.
- Data quality OK.
- Risk budget OK.

## S2 breakout/retest

V1 priority. Measure simple breakout, breakout+retest and breakout+flow confirmation
separately. Remove the retest requirement if waiting for it does not improve net results.

## S3 VWAP mean reversion

Low priority. Produce paper analysis only in sideways/low-trend regimes with a
deviation large enough to cover costs.
