#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
TS="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="runtime/backups/signal-desk-backup-$TS.tar.gz"
mkdir -p runtime/backups
tar --exclude='runtime/backups' -czf "$OUT" config schemas PROJECT_STATE.md CHANGELOG.md runtime/data 2>/dev/null || true
echo "$OUT"
