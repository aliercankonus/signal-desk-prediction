#!/usr/bin/env bash
# One-time root-terminal setup; this script does not deploy the application.
set -Eeuo pipefail
repo='' agent_user='' key_comment='' key_fingerprint='' project='' expected_host=''
usage() { echo 'usage: bash scripts/install-host-gateway.sh --repo ABSOLUTE_PATH --agent-user USER --key-comment COMMENT --key-fingerprint SHA256:... --project EXISTING_COMPOSE_PROJECT --expected-host HOST' >&2; exit 2; }
while (($#)); do
  case "$1" in
    --repo) repo="${2-}"; shift 2 ;;
    --agent-user) agent_user="${2-}"; shift 2 ;;
    --key-comment) key_comment="${2-}"; shift 2 ;;
    --key-fingerprint) key_fingerprint="${2-}"; shift 2 ;;
    --project) project="${2-}"; shift 2 ;;
    --expected-host) expected_host="${2-}"; shift 2 ;;
    *) usage ;;
  esac
done
[[ $(id -u) -eq 0 ]] || { echo 'Run in a VPS root terminal' >&2; exit 1; }
[[ -n "$expected_host" && "$(hostname)" == "$expected_host" ]] || { echo 'Host mismatch' >&2; exit 1; }
[[ "$repo" == /* && -d "$repo/.git" && -f "$repo/scripts/host-gateway.sh" ]] || usage
[[ "$agent_user" =~ ^[a-z_][a-z0-9_-]*$ && "$project" =~ ^[a-z0-9][a-z0-9_-]*$ && "$key_comment" =~ ^[a-zA-Z0-9_-]+$ && "$key_fingerprint" =~ ^SHA256:[A-Za-z0-9+/]+$ ]] || usage
[[ -f "$repo/.env" ]] || { echo 'Existing .env required' >&2; exit 1; }
[[ "$(grep -E '^COMPOSE_PROJECT_NAME=' "$repo/.env" || true)" == "COMPOSE_PROJECT_NAME=$project" ]] || { echo 'Existing Compose project mismatch' >&2; exit 1; }
agent_home=$(getent passwd "$agent_user" | cut -d: -f6)
[[ -n "$agent_home" && -d "$agent_home" && ! -L "$agent_home" ]] || { echo 'Existing dedicated agent home required' >&2; exit 1; }
auth="$agent_home/.ssh/authorized_keys"
[[ -f "$auth" && ! -L "$auth" ]] || { echo 'Existing authorized_keys required' >&2; exit 1; }
# Require exactly one active key and the expected comment. Fail rather than overwrite other access.
mapfile -t entries < <(grep -Ev '^[[:space:]]*(#|$)' "$auth" || true)
[[ ${#entries[@]} -eq 1 ]] || { echo 'Expected exactly one active authorized key' >&2; exit 1; }
read -r -a fields <<< "${entries[0]}"
n=${#fields[@]}
[[ $n -eq 4 && "${fields[1]}" == ssh-ed25519 && "${fields[3]}" == "$key_comment" && "${fields[2]}" =~ ^[A-Za-z0-9+/]+={0,2}$ ]] || { echo 'Expected single ed25519 key/comment not found' >&2; exit 1; }
# Never silently discard from=, expiry, or other pre-existing key restrictions.
[[ "${fields[0]}" == 'restrict,command="/usr/bin/hostname"' || "${fields[0]}" == 'restrict,command="/usr/local/libexec/signal-desk/dispatch"' ]] || { echo 'Unexpected key options; review manually before installation' >&2; exit 1; }
key="${fields[1]} ${fields[2]} ${fields[3]}"
key_info=$(printf '%s\n' "$key" | ssh-keygen -lf - -E sha256) || { echo 'Invalid SSH key' >&2; exit 1; }
actual_fingerprint=$(awk '{print $2}' <<< "$key_info")
[[ "$actual_fingerprint" == "$key_fingerprint" ]] || { echo 'SSH key fingerprint mismatch' >&2; exit 1; }
[[ -f "$repo/config/config.yaml" ]] || { echo 'Active config required' >&2; exit 1; }
grep -Eq '^[[:space:]]*mode:[[:space:]]*paper[[:space:]]*$' "$repo/config/config.yaml" || { echo 'Paper mode required' >&2; exit 1; }
grep -Eq '^[[:space:]]*execution_enabled:[[:space:]]*false[[:space:]]*$' "$repo/config/config.yaml" || { echo 'Disabled execution required' >&2; exit 1; }
bash -n "$repo/scripts/host-gateway.sh" "$repo/scripts/host-gateway-dispatch.sh"
command -v visudo >/dev/null || { echo 'visudo required' >&2; exit 1; }
command -v sudo >/dev/null || { echo 'sudo required' >&2; exit 1; }
command -v runuser >/dev/null || { echo 'runuser required for write-access check' >&2; exit 1; }
runuser -u "$agent_user" -- true || { echo 'Cannot verify agent permissions' >&2; exit 1; }
# The account must not be able to replace the checkout, privileged inputs or its home.
path="$repo"
while [[ "$path" != / ]]; do
  if runuser -u "$agent_user" -- test -w "$path"; then
    echo "Agent can write repository path: $path" >&2; exit 1
  fi
  path=$(dirname -- "$path")
done
path=$(dirname -- "$agent_home")
while [[ "$path" != / ]]; do
  if runuser -u "$agent_user" -- test -w "$path"; then
    echo "Agent can replace home through: $path" >&2; exit 1
  fi
  path=$(dirname -- "$path")
done
permission_list=$(mktemp)
trap 'rm -f -- "$permission_list"' EXIT
# Check every source/config/Git path, not only the checkout root; prune only
# generated data excluded from the Docker build context.
find "$repo" \( -path "$repo/runtime" -o -path "$repo/.venv" -o -path "$repo/data" -o -path "$repo/logs" \) -prune -o -print0 > "$permission_list"
while IFS= read -r -d '' path; do
  if runuser -u "$agent_user" -- test -w "$path"; then
    echo "Agent can write privileged input: $path" >&2; exit 1
  fi
done < "$permission_list"
rm -f -- "$permission_list"
trap - EXIT
# Keep the account's home and SSH files root-owned so it cannot replace its own forced key.
[[ ! -L "$agent_home/.ssh" ]] || { echo 'Symlinked .ssh denied' >&2; exit 1; }
install -d -o root -g root -m 755 /usr/local/libexec/signal-desk /etc/signal-desk
install -o root -g root -m 755 "$repo/scripts/host-gateway.sh" /usr/local/libexec/signal-desk/host-gateway
install -o root -g root -m 755 "$repo/scripts/host-gateway-dispatch.sh" /usr/local/libexec/signal-desk/dispatch
conf_tmp=$(mktemp /etc/signal-desk/.host-gateway.XXXXXXXX)
sudo_tmp=$(mktemp /etc/sudoers.d/.signal-desk.XXXXXXXX)
trap 'rm -f -- "$conf_tmp" "$sudo_tmp"' EXIT
printf 'repo=%q\nproject=%q\nexpected_host=%q\n' "$repo" "$project" "$expected_host" > "$conf_tmp"
chown root:root "$conf_tmp"; chmod 600 "$conf_tmp"
printf '%s\n' "Defaults:$agent_user env_reset, secure_path=\"/usr/sbin:/usr/bin:/sbin:/bin\"" \
  "$agent_user ALL=(root) NOPASSWD: /usr/local/libexec/signal-desk/host-gateway status, /usr/local/libexec/signal-desk/host-gateway validate, /usr/local/libexec/signal-desk/host-gateway deploy" > "$sudo_tmp"
chown root:root "$sudo_tmp"; chmod 440 "$sudo_tmp"
visudo -cf "$sudo_tmp" >/dev/null
# Close the account's writable path before changing the key authorization.
chown root:root "$agent_home" "$agent_home/.ssh" "$auth"
chmod 755 "$agent_home"; chmod 755 "$agent_home/.ssh"; chmod 644 "$auth"
auth_tmp=$(mktemp "$agent_home/.ssh/.authorized_keys.XXXXXXXX")
trap 'rm -f -- "$conf_tmp" "$sudo_tmp" "$auth_tmp"' EXIT
printf 'restrict,command="/usr/local/libexec/signal-desk/dispatch" %s\n' "$key" > "$auth_tmp"
chown root:root "$auth_tmp"; chmod 644 "$auth_tmp"
mv -f -- "$conf_tmp" /etc/signal-desk/host-gateway.conf
mv -f -- "$auth_tmp" "$auth"
# Publish privilege only after the forced SSH key is effective. A failure here
# leaves the key restricted and the gateway unavailable, not an open shell.
mv -f -- "$sudo_tmp" /etc/sudoers.d/signal-desk-host-gateway
echo 'HOST_GATEWAY_READY: status validate deploy (application not deployed)'
