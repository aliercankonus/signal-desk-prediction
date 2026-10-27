#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python -m signal_desk.tools.validate_all --config "${SIGNAL_DESK_CONFIG:-config/config.yaml}"
python -m pytest tests/schema tests/config -q
