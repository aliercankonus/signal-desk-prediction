#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || cp .env.example .env
[ -f config/config.yaml ] || cp config/config.example.yaml config/config.yaml
mkdir -p runtime/data/{raw,features,ledger,models,reports,backups,status}
python -m signal_desk.tools.validate_all --config config/config.yaml
printf 'bootstrap_ok paper_only=true\n'
