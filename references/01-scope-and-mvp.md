# 01 — Scope and MVP

## V0 scope

V0 starts with **Binance BTCUSDT spot paper-only** and includes all system
components. Full scope means building the market data, storage, feature, prediction
interface, strategy, risk, decision, paper execution, EOD, alarms, backup/restore
and portable deployment chain, not simultaneous success for every strategy.

## V0 components

- Binance Spot market-data adapter.
- BTCUSDT raw event storage.
- Local order book state and resync.
- Replay-compatible feature engine.
- Baseline prediction interface.
- Strategy catalog with ordered activation.
- Risk Engine and Decision Engine.
- Paper execution and fill simulation.
- EOD reporting.
- Observability and alarms.
- Docker Compose portable deployment.
- Backup/restore.
- 100 GB default + 200 GB migration plan.

## Outside V0

- Real orders.
- Trading API keys, withdrawals/deposits or real money.
- Futures/perpetual products/leverage.
- Profit guarantees.
- Symbols other than BTC.
- Ruflo/ECC runtime dependencies.

## First working vertical slice

`Binance BTCUSDT sample feed → raw event → local book → feature snapshot → S1 signal → risk check → decision → paper fill → EOD`.

## Deployment and test readiness definitions

- Specification ready: skill, schemas, config and acceptance gates complete.
- Deployment ready: Docker skeleton, preflight, bootstrap, health endpoints and clean-host test pass.
- Paper-run ready: Binance collector, replay, features, decisions, paper ledger and EOD run in paper mode for at least 24 hours.
