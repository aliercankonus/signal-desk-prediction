# Project State

Status: runnable skeleton package updated to v16.

## Readiness

- Specification readiness: high.
- G0/G1 local readiness: implemented and locally tested.
- G2 collector readiness: Binance mapping and gap detection implemented; live network smoke test pending.
- G3 replay/feature readiness: basic replay and feature snapshots implemented; live/replay parity pending.
- EOD readiness: skeleton counts implemented; PnL/model evaluation pending.
- Deployment readiness: Docker files exist but Docker runtime not validated in this environment.
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
