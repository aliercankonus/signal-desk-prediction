#!/usr/bin/env bash
# Installed root-owned. Repository scripts executed by validate/deploy are trusted code.
set -Eeuo pipefail
[[ $# -eq 1 ]] || { echo 'Exactly one operation is required' >&2; exit 2; }
case "$1" in status|validate|deploy) operation="$1" ;; *) echo 'Unknown operation' >&2; exit 2 ;; esac
[[ $(id -u) -eq 0 ]] || { echo 'Root required' >&2; exit 1; }
[[ -f /etc/signal-desk/host-gateway.conf ]] || { echo 'Gateway configuration missing' >&2; exit 1; }
# This configuration is installed root:root 0600, never writable by the SSH account.
source /etc/signal-desk/host-gateway.conf
[[ "$(hostname)" == "$expected_host" ]] || { echo 'Unexpected host' >&2; exit 1; }
[[ -d "$repo/.git" && -f "$repo/docker-compose.yml" && -f "$repo/config/config.yaml" && -f "$repo/.env" ]] || { echo 'Existing checkout/config required; refusing to initialize' >&2; exit 1; }
cd -- "$repo"
# Refuse a mismatched Compose namespace, which would create a different data volume.
existing_project=$(grep -E '^COMPOSE_PROJECT_NAME=' .env || true)
[[ "$existing_project" == "COMPOSE_PROJECT_NAME=$project" ]] || { echo 'Compose project differs from existing .env' >&2; exit 1; }
# These checks are guardrails, not a YAML parser. Application validation remains mandatory.
grep -Eq '^[[:space:]]*mode:[[:space:]]*paper[[:space:]]*$' config/config.yaml || { echo 'Paper mode not found' >&2; exit 1; }
grep -Eq '^[[:space:]]*execution_enabled:[[:space:]]*false[[:space:]]*$' config/config.yaml || { echo 'Execution is not disabled' >&2; exit 1; }
compose() { docker compose -p "$project" -f "$repo/docker-compose.yml" "$@"; }
if [[ "$operation" != status ]]; then
  git -c "safe.directory=$repo" diff --quiet HEAD -- . ':(exclude)config/config.yaml' || { echo 'Tracked repository code differs from HEAD' >&2; exit 1; }
  untracked=$(git -c "safe.directory=$repo" ls-files --others --exclude-standard) || { echo 'Git inventory failed' >&2; exit 1; }
  [[ -z "$untracked" ]] || { echo 'Untracked repository files require review/commit' >&2; exit 1; }
fi
case "$operation" in
  status)
    echo "HOST=$(hostname) PROJECT=$project"
    compose ps
    ;;
  validate)
    compose config -q
    compose build collector
    compose run --rm --no-deps collector python -m signal_desk.tools.validate_all --config config/config.yaml
    compose run --rm --no-deps collector python -m pytest -q
    ;;
  deploy)
    # Existing deployment gate prevents running while this project's collector is active.
    exec bash "$repo/scripts/deploy.sh" --project "$project" --expected-host "$expected_host"
    ;;
esac
