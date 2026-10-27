# Project State

Status: runnable skeleton package updated to v16.

## Readiness

- Specification readiness: high.
- G0/G1 local readiness: implemented and locally tested.
- Collector readiness: bounded 25/1,000-record VPS live smoke passed; optional continuous candidate locally tested, VPS acceptance pending.
- G3 replay/feature readiness: basic replay and feature snapshots implemented; live/replay parity pending.
- EOD readiness: skeleton counts implemented; PnL/model evaluation pending.
- Deployment readiness: user verified API image build, 24 tests and paper-only healthy API on VPS; new continuous collector image/resource limits pending.
- Paper run readiness: not ready until full ledger, paper executor loop and EOD PnL pass.
- Live trading readiness: out of scope.

## Current hard decisions

- V0: Binance BTCUSDT spot paper-only.
- Runtime: Docker Compose portable deployment.
- Disk profiles: 100 GB default, 200 GB migration supported.
- RAM profile: 2 GB.
- Strategy primary: S1 order-flow continuation.
- Paper-fill acceptance: conservative mode.

## v16 implementation status — 2026-10-26

Implemented:

- Config and JSON schema validation tooling.
- Binance BTCUSDT snapshot/delta/trade mapping utilities.
- Binance L2 order book state with gap detection.
- Collector `--mode idle` and `--mode once` REST snapshot smoke mode.
- Health API returning paper-only status.
- Conservative paper-fill rules including stop-first behavior.
- Deterministic minimal Decision Engine skeleton.
- Basic causal feature engine.
- Replay runner from raw JSONL events to feature JSONL snapshots.
- Storage manifest generator.
- EOD skeleton report generator.
- Alarm manager.
- Bootstrap, preflight, healthcheck, backup, restore and 200GB migration scripts.

Local validation performed in the assistant container:

```bash
PYTHONPATH=src python -m pytest -q
# 16 passed
PYTHONPATH=src python -m signal_desk.tools.validate_all --config config/config.example.yaml
# schemas_ok=14 config_version=cfg-v16-example-001 mode=paper
PYTHONPATH=src ./scripts/bootstrap.sh
# bootstrap_ok paper_only=true
```

Not yet validated: Docker build/compose runtime, live Binance network snapshot, VPS resource limits, long-running collector, live/replay parity, full paper ledger, full EOD PnL/model evaluation.

## Time Machine — 2026-10-27

- Kullanıcı kabulü: replay'den ayrı `timemachine` araştırma feature'ı.
- Kaynak incelemesi ve BTC uyarlama sözleşmesi: references/16-timemachine.md.
- Karar: decision_log/2026-10-27-timemachine.md.
- Durum: specification accepted; implementation, schemas, config wiring and tests pending.
- Çalışan runtime, replay ve test sayısı değiştirilmedi. VPS kontrolü/smoke hâlâ sıradaki iş.

## VPS evidence and stream bootstrap correction — 2026-10-27

User-reported VPS evidence at /docker/hermes-agent-qbva/data/signal-desk-prediction:
- Docker API image built; config/schema validation passed with cfg-v16-example-001.
- Existing test suite: 16 passed in 0.40s; API healthy, paper, execution_enabled=false,
  ready_for_enter=false. REST snapshot wrote raw events.
- Live WebSocket smoke FAILED: exit 2, gap_count=1, RESYNCING. Not a feed acceptance.
- Bootstrap fix now has 24 locally passing tests and config/schema validation.
- New image build and live retest on VPS pending; no 24h soak or profitability claim.
- Fix/research source and bounds: decision_log/2026-10-27-binance-stream-bootstrap.md.
- Continuous reconnect/resync and resource soak are still pending.

## Continuous collector candidate — 2026-10-27
- User reported VPS bootstrap acceptance: 24 passed; 25 records (19 depth/5 trade)
  and 1,000 records (275 depth/724 trade), both gap_count=0, exit=0.
- Bootstrap fix merged to main at 76d00b8 and checked out on VPS.
- Continuous recovery candidate: local 49-test suite and schema/config validation pass.
- Added bounded retry/resync, cancellable snapshot requests, storage limits and counters.
- Config collector section is optional; preserve the user's active config/config.yaml.
- Compose remains idle. No unattended collector has been started by this change.
- Next single task: rebuild/test candidate collector on VPS, then bounded 60s run.
- Pending: actual resource measurements, live fault injection, soak, retention,
  replay parity, full paper ledger/EOD/model results.

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
