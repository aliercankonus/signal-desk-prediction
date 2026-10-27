# 17 — Continuous collector candidate

## Acceptance status
Implementation and local tests complete; VPS continuous-mode validation pending.
Previous bounded stream smoke passed on VPS: 25 records and then 1,000 records,
gap_count=0 and exit=0; 24 previous tests passed there. That does not prove a 24h run.
Time Machine remains specification-only. No trading keys or real execution.

## Modes and ownership
- `stream --max-events N`: bounded smoke, returns on failure.
- `continuous --max-run-seconds 60`: recovery loop with a bounded validation duration.
- `continuous`: runs until signal or HALT, but do not start unattended until VPS acceptance.
- Default Compose collector stays `idle`. No automatic Docker restart bypasses HALT.
- Use the collector service (512 MiB, 0.75 CPU, 64 PIDs), not the smaller API service,
  to test the recovery candidate. Log rotation is 10 MiB × 3 files.
- One continuous writer per data volume is enforced with a file lock. Do not run a
  separate once/stream smoke writer while continuous mode is active.

## Recovery contract
Every recovery closes the previous connection, discards its in-memory book and
buffers a new WS before fetching a fresh snapshot. No old book is reused.
Each session has an ID in the status and raw event data_quality.
Maintain cumulative counters for persisted records, depth, trades, reconnects and gaps.
Gaps, bounded-buffer overflow, socket close, serverShutdown, stale data and transient
network/5xx failures trigger RESYNCING with backoff. No execution path is enabled.
Malformed data, storage failure and HTTP <500 errors (including 418/429) HALT.
Retry delays start at 1s, double and cap at 30s. At 5 consecutive failures HALT.
Opening a socket or applying one snapshot does not reset the budget: require
60s of synchronized, fresh progress. No auto-restart loop circumvents this budget.
A process restart intentionally begins a new budget; it is not automatically invoked.

## Central config and bounds
Optional `collector` section is validated by config.schema.json and RecoveryPolicy.
For existing v16 active configs, omitted keys use this one policy definition:
max_failures=5, retry_initial_seconds=1, retry_max_seconds=30,
stable_reset_seconds=60, status_interval_seconds=5, storage_check_seconds=5,
snapshot_timeout_seconds=15. Effective settings are included in status output.
Cross-field retry bounds fail validation. Existing config/config.yaml is not overwritten.

Existing memory/WS bounds remain: app queue 256, message 256 KiB, WS queue 16;
these are engineering caps, not measured production capacity.
Existing market_data.stale_l2_ms and stale_trades_ms bound feed freshness.
Trade traffic cannot hide a stale depth stream. Duplicate depth does not refresh depth.
A depth bridge, not trade traffic alone, is necessary to enter RUNNING.
Snapshot HTTP runs in a child process with a response cap of 2 MiB. Deadline or
shutdown kills and reaps that process; cancellation does not leave a REST thread running.

## Storage and status
Retain raw JSONL (the current implementation is not Zstd despite the placeholder
raw_codec label). Inventory raw file bytes once on continuous startup, then account
for persisted bytes incrementally. Enforce retention.raw_pool_gb as GiB before writes.
Check filesystem usage at startup and at most every 5s against alarms.disk_halt_pct.
HALT at raw quota/disk limit. No deletion, compression, archival or TTL automation added.
This does not reserve disk against other writers, so keep only one data collector active.
Status updates use atomic replacement. On intentional stop write STOPPED and clear
session_synchronized. Status timestamps must be checked by consumers; they are not
an integrated Decision Engine permission. API ready_for_enter remains false.

## VPS acceptance sequence
From the candidate branch, validate Compose and rebuild collector:
```bash
docker compose -p signal-desk-prediction config -q
docker compose -p signal-desk-prediction build collector
docker compose -p signal-desk-prediction run --rm --no-deps collector python -m pytest -q
```
After those pass, run the bounded candidate:
```bash
docker compose -p signal-desk-prediction run --rm --no-deps collector \
  python -u -m signal_desk.collector.binance_collector \
  --mode continuous --max-run-seconds 60 --config config/config.yaml
echo "CONTINUOUS_EXIT_CODE=$?"
```
Require exit 0, reason max_run_seconds_reached, persisted depth and trade counts >0,
no HALT, and explain any gap/reconnect counters. Exit 2 means the duration ended
without a currently synchronized session; do not accept it as a feed pass.
Exit 3 means HALT or a second continuous writer.
Do not run another smoke test concurrently or delete runtime data to make tests pass.
Then measure actual memory/CPU/disk growth and exercise live recovery before a soak.
No 24h run, replay parity, backup/restore, EOD PnL or profitability acceptance here.

## Evidence
Local suite: 49 passed; config/schema validation passed. Mock fault tests cover
gaps, disconnects, retry exhaustion/reset, HTTP refusal, stale depth, disk/raw caps,
deadline cancellation and a second writer. Local HTTP integration exercises the
actual snapshot child process for HTTP 200 and 429. VPS resource enforcement,
60s continuous run and live network fault recovery are pending.

## 2026-10-27 — Stale incident follow-up
User-reported first continuous VPS run: 817 persisted records (130 depth, 684 trade,
3 snapshots), gap_count=0, two stale-depth resyncs. Final exit code was not provided.
Do not accept stability/soak or merge on that output alone.
Per-event schema reloading/meta-validation was found in the hot path and replaced
with bounded checked-validator reuse. Instance validation and fsync remain enabled.
The 2s/3s configured freshness limits and recovery behavior are unchanged.
Add current-event age, depth receipt/application age, queue high-water, event-loop lag,
validation and write/IO timing. Keep last failure diagnostics across a later session.
These measurements separate observed receipt/processing delays; no network root cause
has been proven. Main remains unchanged.
Local suite now 53 passed; config/schema validation passed.
An isolated local 100-event validation benchmark was 0.6502s before vs 0.0203s after;
this is not an end-to-end or VPS performance claim. VPS rebuild and 60s repeat pending.
