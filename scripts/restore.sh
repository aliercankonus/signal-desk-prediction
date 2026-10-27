#!/usr/bin/env bash
set -euo pipefail
if [ $# -ne 1 ]; then echo "usage: $0 backup.tar.gz" >&2; exit 2; fi
cd "$(dirname "$0")/.."
tar -xzf "$1"
python -m signal_desk.tools.validate_all --config config/config.yaml
printf 'restore_validated\n'
