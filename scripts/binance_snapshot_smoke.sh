#!/usr/bin/env bash
set -euo pipefail
CONFIG_PATH="${1:-config/config.yaml}"
PYTHONPATH=src python -m signal_desk.collector.binance_collector --mode once --config "$CONFIG_PATH"
PYTHONPATH=src python -m signal_desk.api.healthcheck "${HEALTH_URL:-http://127.0.0.1:8080/health}" || true
