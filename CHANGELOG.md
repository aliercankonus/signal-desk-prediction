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

## 2026-10-27 — Binance stream bootstrap fix
- Open and buffer WS before the REST snapshot; REST no longer blocks the receiver.
- Retry old snapshots within a bounded budget, discard covered deltas, require depth bridge.
- Preserve previous update ID, stop on genuine gaps/overflow, print failure JSON.
- Added 8 mocked stream regression tests; full local suite 24 passed.
- VPS rebuild/live retest pending; continuous collector readiness not established.

## 2026-10-27 — Opt-in continuous collector candidate
- Added bounded recovery/backoff, new snapshot and book on every reconnect, cumulative
  counters and session tags; require sustained healthy progress before resetting retries.
- Added killable REST child, signal/deadline shutdown, permanent HTTP HALT and storage caps.
- Added optional validated collector policy; keep current active config compatible.
- Added collector CPU/PID/log limits; Compose default remains idle, restart disabled.
- Local suite 49 passed, config/schema validation passed; VPS continuous validation pending.

## 2026-10-27 — Stale pipeline diagnostics and schema reuse
- Reuse checked validators with bounded identity-keyed cache; still validate each event.
- Add receipt/application age, queue, loop-lag, validation/write/IO diagnostics.
- Preserve last failure diagnostics across resync. Keep freshness/fsync/CPU limits.
- Local suite 53 passed; first 60s VPS run had two stale resyncs, repeat pending.

## 2026-10-27 — Read-only captured-session audit candidate

- Add record-bounded session filtering, JSON/schema/semantic and sequence checks.
- Compare expected persisted counts; report incremental file hashes and input changes.
- Preserve raw data; no event-ID accumulation, full-file list loading or replay claims.
- Local suite 67 passed and config/schema validation passed; actual host audit pending.

## 2026-10-27 — One-command installation candidate

- Add install/deploy entry points, optional fresh-Ubuntu Docker prerequisites and scoped checkout reuse.
- Preserve active config/volume; gate build/config/tests/public smoke/API health and write local manifest/logs.
- Add loopback-default configurable API binding and exclude private runtime/config from build context.
- Publish portable installation and full generic command catalog; refresh sanitized technical checkpoint.
- Candidate includes validated PR #3 audit source. Local suite 88 passed; actual installer/clean-host validation pending.

## 2026-10-27 — English repository documentation and installation follow-up

- Translate repository skills, setup guides, research contracts and decision records
  to English; keep identifiers, commands and contract semantics unchanged.
- Require English for future repository documentation, comments and runtime messages,
  independently of the user's conversation language.
- Record the approved installer/audit merge and user-reported existing-VPS DEPLOY_OK.
- Independent clean-host installation, restore and full paper-readiness gates remain pending.
