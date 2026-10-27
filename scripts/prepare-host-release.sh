#!/usr/bin/env bash
# Approve an operator-cloned, reviewed full commit in a protected checkout.
# Root-terminal only; never run through the restricted SSH key.
set -Eeuo pipefail
umask 077
release_dir='' approved_commit='' config_dir='' agent_container='' project='' expected_host='' settings=''
usage() { echo 'usage: prepare-host-release.sh --dir ROOT_CHECKOUT --commit FULL_SHA --config-dir ROOT_APPROVED_DIR --agent-container NAME --project EXISTING_PROJECT --expected-host HOST --settings ROOT_OWNED_JSON_PATH' >&2; exit 2; }
while (($#)); do
  (($# >= 2)) || usage
  case "$1" in
    --dir) release_dir="$2" ;;
    --commit) approved_commit="$2" ;;
    --config-dir) config_dir="$2" ;;
    --agent-container) agent_container="$2" ;;
    --project) project="$2" ;;
    --expected-host) expected_host="$2" ;;
    --settings) settings="$2" ;;
    *) usage ;;
  esac
  shift 2
done
[[ $(id -u) -eq 0 ]] || { echo 'VPS root terminal required' >&2; exit 1; }
[[ "$(hostname)" == "$expected_host" && -n "$expected_host" ]] || { echo 'Host mismatch' >&2; exit 1; }
[[ "$approved_commit" =~ ^[a-f0-9]{40}$ && "$project" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || usage
[[ "$release_dir" == /srv/* && "$settings" == /etc/signal-desk/releases/* ]] || usage
[[ ! -e "$settings" && ! -L "$settings" ]] || { echo 'Approval already exists; refusing replacement' >&2; exit 1; }
[[ -d "$release_dir/.git" && -f "$release_dir/scripts/host_release_guard.py" ]] || { echo 'Root-cloned checkout required' >&2; exit 1; }
guard=/usr/local/libexec/signal-desk/release-guard.py
[[ -f "$guard" && ! -L "$guard" ]] || { echo 'Independently installed root-owned release guard required' >&2; exit 1; }
bash -n "$release_dir/scripts/prepare-host-release.sh"
python3 "$guard" check-checkout --dir "$release_dir" \
  --commit "$approved_commit" --config-dir "$config_dir" \
  --agent-container "$agent_container" --project "$project" --settings "$settings"
# Copy only operator-approved settings; never print their contents or create a
# new Compose project. Existing data is in the project-scoped Docker volume.
chmod 700 "$release_dir"
install -o root -g root -m 600 "$config_dir/.env" "$release_dir/.env"
install -o root -g root -m 600 "$config_dir/config.yaml" "$release_dir/config/config.yaml"
agent_container_id=$(docker inspect --format '{{.Id}}' "$agent_container")
python3 "$guard" approve \
  --repo "$release_dir" --approved-commit "$approved_commit" --project "$project" \
  --expected-host "$expected_host" --agent-container-id "$agent_container_id" \
  --settings "$settings"
echo 'Release checkout approved; SSH authorization remains unchanged.'
