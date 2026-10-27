# 01 — Scope and MVP

## V0 kapsamı

V0, **Binance BTCUSDT spot paper-only** ile başlar ve tüm sistem bileşenlerini içerir. “Tüm kapsam” her stratejinin eş zamanlı başarı testi değil; market data, storage, feature, prediction interface, strategy, risk, decision, paper execution, EOD, alarms, backup/restore ve portable deployment zincirinin kurulmasıdır.

## V0 bileşenleri

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

## V0 dışı

- Gerçek emir.
- Trading API key, çekim/yatırım veya gerçek para.
- Futures/perpetual/kaldıraç.
- Kâr garantisi.
- BTC dışı semboller.
- Ruflo/ECC runtime dependency.

## İlk çalışan dikey kesit

`Binance BTCUSDT sample feed → raw event → local book → feature snapshot → S1 signal → risk check → decision → paper fill → EOD`.

## Deployment ve test readiness tanımı

- Specification ready: skill + schemas + config + acceptance gates tamam.
- Deployment ready: Docker skeleton, preflight, bootstrap, health endpoints ve clean-host test geçer.
- Paper-run ready: Binance collector, replay, feature, decision, paper ledger ve EOD en az 24 saat paper çalışır.
