# 09 — EOD Report

Run EOD daily and make it idempotent. A rerun for the same day produces a revision.

## Human-readable report

- Data coverage.
- Gaps/stale periods.
- Number of predictions.
- Number of signals.
- Enter/blocked/wait counts.
- Paper trades.
- Gross/net paper PnL.
- Fees/slippage estimate.
- Stop/TP/time-stop outcomes.
- Markout summary.
- Model calibration.
- Strategy by regime.
- Top failure reasons.
- Alarms and halts.
- Next recommended research action.

## JSON contract

Use `schemas/eod_report.schema.json`.

## Midnight rules

- Link positions crossing midnight to their prior-day opening evidence and closing-day result.
- Late fill corrections produce EOD revisions.
- Do not leak final-test results back into model selection through EOD.
