# 10 — EOD Report

Produce a human-readable summary and a JSON artifact. A single daily report is
insufficient for model selection.

## Contents

- Data coverage.
- Gap/stale/reconnect counts.
- Disk/RAM/cache status.
- Signal counts: produced, blocked, entered, exited.
- Gross/net results by strategy.
- Fee/slippage impact.
- Paper-fill mode breakdown.
- Markout summary.
- Model accuracy/calibration metrics.
- Risk: max drawdown, daily loss latch, stops.
- Alarm summary.
- Research recommendations.

## Revision and idempotency

- Reports may be regenerated for the same day.
- Increment `revision` for late/reconciled fills.
- Do not overwrite previous revisions.
- Do not leak final-test results into model selection.

## Day boundary

Configure Europe/Amsterdam or UTC explicitly. UTC trading days are recommended for
V0; user reports may additionally show Amsterdam local time.

## Example JSON fields

Required `eod_report.schema.json` fields: summary, data_quality, strategy_results,
model_results, paper_results, alarms, revisions.
