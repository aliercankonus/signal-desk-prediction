#!/usr/bin/env bash
set -euo pipefail
CONFIG_PATH="${1:-config/config.yaml}"
MAX_EVENTS="${MAX_EVENTS:-25}"
PYTHONPATH=src python -m signal_desk.collector.binance_collector --mode stream --config "$CONFIG_PATH" --max-events "$MAX_EVENTS"
