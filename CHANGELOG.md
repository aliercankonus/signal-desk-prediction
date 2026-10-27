# Changelog

## v14

- Clarified V0 as Binance BTCUSDT spot paper-only.
- Added Binance market data adapter specification.
- Added missing schemas: risk_state, ledger_entry, model_manifest, run_manifest, config, alarm_event, storage_manifest.
- Expanded paper-fill modes with explicit rules.
- Centralized config contract.
- Added deployment skeleton requirements.
- Expanded acceptance gates G0-G9.
- Added research decision policy: no new technical decision without source and test impact.
- Added 100 GB to 200 GB migration runbook.


## v14 — implementation skeleton

- Added runnable Python skeleton for G0-G1 validation.
- Added Binance BTCUSDT event mapping and L2 sequence gap detection primitives for G2.
- Added API health server and Dockerfile/Compose skeleton.
- Added scripts for bootstrap, preflight, healthcheck, backup, restore, and 200GB migration runbook.
- Added pytest suite: schemas, config, Binance mapping, decision idempotency, paper-fill conservative stop-first, deployment file presence.
- Verified locally with 8 passing tests and config/schema validation.
- Docker runtime and live Binance smoke test remain pending.


## v15 — replay, EOD and alarm skeleton

- Added causal feature engine for L2 top-of-book and trade delta snapshots.
- Added replay runner that converts validated raw market events into validated feature snapshots.
- Added storage manifest generator with sha256/byte/kind metadata.
- Added EOD report skeleton with raw/feature/ledger counts and schema validation.
- Added alarm manager for disk, RAM, stale L2 and ledger-write failure actions.
- Expanded tests from 8 to 16: features, replay, storage manifest, EOD, alarms and order book gap handling.
- Verified locally with 16 passing tests plus config/schema validation and bootstrap.
- Docker runtime, live Binance smoke test, long-running collector, full paper ledger and full PnL EOD remain pending.

## v16 — VPS smoke deployment pack

- Added VPS deployment runbook.
- Added Makefile convenience targets.
- Added Binance REST snapshot and short websocket smoke scripts.
- Added collector `stream` mode with max-events guard for public-data smoke tests.
- Added GitHub setup instructions.
- No API keys or real order execution added.

## 2026-10-27 — Time Machine feature specification

- Added a separate timemachine research feature contract and pinned source review.
- Separated synthetic Monte Carlo scenarios from historical strategy-rule tests and existing event replay.
- Defined BTC/UTC, costs, stop-gap, causality, resource and acceptance requirements.
- Documentation/skill update only; no simulator implementation or newly passing runtime tests.
