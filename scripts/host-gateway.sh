#!/usr/bin/env bash
# Installed root-owned. SSH cannot select a ref, update code or promote releases.
set -Eeuo pipefail
[[ $# -eq 1 ]] || { echo 'Exactly one operation is required' >&2; exit 2; }
case "$1" in status|validate|deploy) operation="$1" ;; *) echo 'Unknown operation' >&2; exit 2 ;; esac
[[ $(id -u) -eq 0 ]] || { echo 'Root required' >&2; exit 1; }
# This installed, root-owned verifier checks the full approved SHA, Git changes,
# root ownership, path ancestry, pinned config hashes and agent container mounts.
verified=$(/usr/bin/python3 /usr/local/libexec/signal-desk/release-guard.py verify \
  --settings /etc/signal-desk/host-gateway.json) || exit 1
mapfile -t release_fields <<< "$verified"
[[ ${#release_fields[@]} -eq 3 ]] || { echo 'Invalid verified release fields' >&2; exit 1; }
repo=${release_fields[0]}; project=${release_fields[1]}; expected_host=${release_fields[2]}
cd -- "$repo"
compose() { docker compose -p "$project" -f "$repo/docker-compose.yml" "$@"; }
case "$operation" in
  status)
    echo "HOST=$expected_host PROJECT=$project"
    compose ps
    ;;
  validate)
    compose config -q
    compose build collector
    compose run --rm --no-deps collector python -m signal_desk.tools.validate_all --config config/config.yaml
    compose run --rm --no-deps collector python -m pytest -q
    ;;
  deploy)
    # The reviewed deployment code preserves the existing project and volume.
    exec bash "$repo/scripts/deploy.sh" --project "$project" --expected-host "$expected_host"
    ;;
esac
