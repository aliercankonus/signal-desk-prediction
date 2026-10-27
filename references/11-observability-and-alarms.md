# 11 — Observability and Alarms

## Alarm levels

| Level | Meaning | Action |
| --- | --- | --- |
| INFO | Normal information | Log |
| WARN | Needs investigation | Include in EOD |
| BLOCK | No new ENTER | Open risk reduction may continue |
| HALT | Critical | No new risk; maintenance/recovery |

## Automatic actions

| Condition | Alarm | Action |
| --- | --- | --- |
| L2 stale | BLOCK | No new ENTER; resync |
| Trades stale | BLOCK | No new ENTER |
| Heartbeat missed | BLOCK | Reconnect/resync |
| Binance gap | BLOCK | Discard local book and bootstrap |
| Disk >85% | BLOCK | No new entries |
| Disk >95% | HALT | Maintenance |
| Ledger write error | HALT | Stop all order intents |
| Model unavailable | WARN/BLOCK | Prediction unavailable; no strategy ENTER |
| Fee stale/missing | BLOCK | No new ENTER |
| Recovery incomplete | BLOCK | No new entries until reconciliation completes |
| RAM >95% | HALT | Worker restart/maintenance |
| Config invalid | HALT | Fail closed at startup |
| Schema validation error | HALT for writer | Quarantine the invalid event |

## Required metrics

- decision_latency p50/p95/p99
- market_data_age_ms
- queue_depth
- raw_write_lag
- feature_compute_ms
- prediction_compute_ms
- risk_check_ms
- paper_fill_latency
- disk_pct
- rss_mb
- restart_count
- duplicate_event_count
- gap_count
- blocked_decision_count
- eod_revision_count

## Health endpoints

- `/health/live`: process alive.
- `/health/ready`: config + storage + market data + ledger + mode ready.
- `/health/paper`: paper-only and execution-disabled confirmation.
- `/metrics`: Prometheus-compatible text or JSON metrics.
