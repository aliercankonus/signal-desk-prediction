#!/usr/bin/env bash
set -euo pipefail
python -m signal_desk.api.healthcheck "${1:-http://127.0.0.1:8080/health}"
