#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
cat <<'EOF'
200GB migration runbook:
1. Stop services cleanly: docker compose down
2. Snapshot/backup volume and config.
3. Resize VPS disk in provider UI.
4. Expand filesystem per OS/provider instructions.
5. Update config.resources.profile=200gb_2gb and disk_total_gb=200.
6. Increase retention.raw_pool_gb according to reference 05.
7. Run scripts/preflight.sh and docker compose up -d.
8. Confirm health, disk alarms, and raw write path.
EOF
