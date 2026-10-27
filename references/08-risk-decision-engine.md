# 08 — Risk and Decision Engine

## Decisions

- `ENTER`: intent to open a new paper position.
- `HOLD`: retain the current position.
- `UPDATE_STOP`: update stop protection without closing the position.
- `EXIT`: request closure/reduction of an open position.
- `WAIT`: no opportunity.
- `BLOCK`: prevent new entries because of data, risk, config or system problems.
- `HALT`: critical system state; take no new risk.

## States

Persist mode, position state, order intent state, ledger state, and risk latch separately.

Position:

- `FLAT`
- `OPENING`
- `OPEN`
- `CLOSING`
- `UNCERTAIN`
- `RECOVERING`

Order intent:

- `PLANNED`
- `RISK_RESERVED`
- `PENDING_SEND`
- `ACKED`
- `PARTIALLY_FILLED`
- `FILLED`
- `CANCEL_REQUESTED`
- `CANCELLED`
- `REJECTED`
- `UNKNOWN`

## Priority order

1. Ledger write failure → HALT.
2. Recovery/reconciliation incomplete → BLOCK.
3. Open risk reduction EXIT/UPDATE_STOP.
4. Daily loss latch.
5. Data freshness gate.
6. Fee/cost gate.
7. Strategy ENTER.
8. HOLD/WAIT.

## Risk defaults

- Risk/trade: 0.25% of starting/current equity, as selected by config policy.
- Daily loss: 1.0% of start-of-day equity.
- Max notional: 10% of equity.
- Max open positions: 1.
- Re-entry cooldown: 60s.
- After-stop cooldown: 300s.

These are initial paper parameters, not validated optima.

## Daily loss behavior

When the daily loss limit triggers:

- BLOCK new ENTER decisions.
- Cancel pending entries.
- Request EXIT for the open quantity.
- If data is stale, do not report exit completion; retain `UNCERTAIN/RECOVERING` state.

Store realized PnL and reliable mark-to-market open PnL separately; do not subtract the same loss twice.

## Idempotency

Derive the order intent ID from a hash of these fields:

- strategy_id
- signal_id
- config_version
- portfolio_version
- feature_snapshot_id
- decision_time
- side
- intended_qty
- stop/tp/time_stop plan hash

If an intent remains uncertain, do not resend it with a new identity; reconcile against the ledger first.

## Risk parameter change policy

- Every risk change creates a new `risk_config_version`.
- Preserve the old risk plan for open positions; evaluate new entries with the new config.
- Apply a lower daily loss limit immediately.
- Increasing the daily loss limit requires manual approval.
