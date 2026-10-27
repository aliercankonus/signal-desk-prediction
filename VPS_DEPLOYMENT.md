# VPS deployment runbook — v16

Status: paper-only smoke deployment. No exchange API key. No real orders.

## 0) Prerequisites

- Ubuntu 24.04/22.04 VPS
- Docker Engine + Docker Compose plugin
- At least 100 GB disk and 2 GB RAM for the current profile
- Outbound HTTPS/WSS access to Binance public endpoints

## 1) Upload and unpack

```bash
mkdir -p ~/signal-desk
cd ~/signal-desk
unzip signal-desk-prediction-v16.zip
cd signal-desk-prediction-v16
```

## 2) Prepare config

```bash
cp .env.example .env
mkdir -p config
cp config/config.example.yaml config/config.yaml
```

Check these before running:

```bash
grep -n "execution_enabled" config/config.yaml
grep -n "symbol" config/config.yaml
grep -n "maker_bps\|taker_bps" config/config.yaml
```

Expected:

- `execution_enabled: false`
- `symbol: BTCUSDT`
- fees are manually verified before interpreting PnL

## 3) Local package checks on VPS

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=src python -m pytest -q
PYTHONPATH=src python -m signal_desk.tools.validate_all --config config/config.yaml
./scripts/preflight.sh
```

## 4) Docker checks

```bash
docker compose config -q
docker compose build
docker compose up -d api maintenance collector
docker compose ps
docker compose logs --tail=100
./scripts/healthcheck.sh
```

## 5) Binance public-data smoke tests

REST snapshot only:

```bash
./scripts/binance_snapshot_smoke.sh config/config.yaml
```

Short public websocket stream test:

```bash
MAX_EVENTS=25 ./scripts/binance_stream_smoke.sh config/config.yaml
```

Expected:

- raw JSONL appears under `runtime/data/raw` if running outside Docker, or under Docker volume if run inside container.
- collector status is `RUNNING` or `STOPPED` with `max_events_reached`.
- any gap leads to `RESYNCING`, not silent continuation.

## 6) Resource check

```bash
docker stats --no-stream
df -h
du -sh runtime data logs 2>/dev/null || true
free -h
```

## 7) Stop

```bash
docker compose down
```

## Current blockers before 24/7 run

- Full live collector service command is not yet enabled by default in compose.
- Replay parity on real captured data is not yet completed.
- Full paper ledger/PnL is not yet implemented.
- EOD is skeleton only.
