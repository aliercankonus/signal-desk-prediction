# 05 — Strategy Catalog

Strategies are grouped by purpose. Each requires separate preregistration, testing
and results.

## Category A — Baseline / No-trade

### S0: No-trade and simple baseline

Measure market movements and model references without opening positions.

- No-trade baseline.
- Midpoint/no-change.
- Simple momentum.
- Cost-only gate.

## Category B — Primary Alpha Candidate

### S1: Order-flow continuation

First primary strategy.

Entry candidate:

- Trade pressure points in the same direction.
- L2 book imbalance/depth changes support it.
- Expected movement covers spread and fees.
- Data quality is healthy.
- No repeated entry on the same signal without a reset.

Exit:

- Fixed stop.
- Take profit.
- Time stop.
- Signal invalidation.
- Risk or data HALT.

### S1b: S1 + cost gate

S1 with a stricter cost filter.

### S1c: S1 + fixed stop/TP

Initial paper acceptance variant. Trailing is disabled.

### S1d: S1 + trailing stop A/B

A separate experiment against fixed stops, not the default.

Trailing rules:

- A long stop can only move upward.
- UPDATE_STOP does not close the position.
- A new prediction does not reset holding duration.
- Keep pending and confirmed stop updates separate.
- Do not lower stops; loosening protection is a manual config change.

## Category C — Structural Price Action

### S2: Breakout and retest

Breakout of the previous range, retest and order-flow confirmation.

Usage:

- After S1.
- Measure whether the retest filter improves net expectancy.
- Fewer trades alone do not establish success.

## Category D — Mean Reversion Candidate

### S3: VWAP mean reversion

Candidate for reversion from VWAP deviations in sideways/low-trend conditions.

Usage:

- Lower-priority exploration.
- Post-cost movement size is critical.
- Do not automatically activate on trending days.

## Strategy sequence

1. S0 baseline.
2. S1 order-flow continuation.
3. S1b cost gate.
4. S1c fixed stop/TP.
5. S1d trailing A/B.
6. S2 breakout/retest.
7. S3 VWAP mean reversion.
