#!/usr/bin/env bash
# Root-terminal activation of an already approved protected checkout; no deployment.
set -Eeuo pipefail
umask 077
settings='' agent_user='' key_comment='' key_fingerprint=''
usage() { echo 'usage: install-host-gateway.sh --settings ROOT_APPROVED_JSON --agent-user DEDICATED_USER --key-comment COMMENT --key-fingerprint SHA256:...' >&2; exit 2; }
while (($#)); do
  (($# >= 2)) || usage
  case "$1" in
    --settings) settings="$2" ;;
    --agent-user) agent_user="$2" ;;
    --key-comment) key_comment="$2" ;;
    --key-fingerprint) key_fingerprint="$2" ;;
    *) usage ;;
  esac
  shift 2
done
[[ $(id -u) -eq 0 ]] || { echo 'VPS root terminal required' >&2; exit 1; }
[[ "$agent_user" =~ ^[a-z_][a-z0-9_-]*$ && "$key_comment" =~ ^[a-zA-Z0-9_-]+$ && "$key_fingerprint" =~ ^SHA256:[A-Za-z0-9+/]+$ ]] || usage
[[ -f "$settings" && ! -L "$settings" ]] || { echo 'Root-approved release settings required' >&2; exit 1; }
# Activation is deliberately one-shot. Never overwrite a working gateway in place.
[[ ! -e /etc/signal-desk/host-gateway.json && ! -L /etc/signal-desk/host-gateway.json && \
   ! -e /etc/sudoers.d/signal-desk-host-gateway && ! -L /etc/sudoers.d/signal-desk-host-gateway ]] || {
  echo 'Gateway already activated or partially activated; root review required' >&2; exit 1;
}
# Parse data, never source a manifest. Refuse newlines and non-absolute repo paths.
release_info=$(python3 - "$settings" <<'PY'
import json, pathlib, sys
try:
    data = json.load(open(sys.argv[1], encoding='utf-8'))
    path = data['repo']
    sha = data['approved_commit']
    assert isinstance(path, str) and path.startswith('/') and '\n' not in path
    assert isinstance(sha, str) and len(sha) == 40 and all(c in '0123456789abcdef' for c in sha)
    print(path + '\n' + sha)
except (OSError, ValueError, KeyError, AssertionError, TypeError):
    sys.exit('Invalid release settings')
PY
)
mapfile -t fields <<< "$release_info"
[[ ${#fields[@]} -eq 2 ]] || { echo 'Invalid release settings fields' >&2; exit 1; }
repo=${fields[0]}; approved_commit=${fields[1]}
[[ -d "$repo/.git" && -f "$repo/scripts/host_release_guard.py" ]] || { echo 'Protected checkout missing' >&2; exit 1; }
# Each file gets its own syntax check. A broken dispatcher must stop BEFORE
# copying privileged files, changing home ownership or replacing authorization.
bash -n "$repo/scripts/host-gateway-dispatch.sh"
bash -n "$repo/scripts/host-gateway.sh"
bash -n "$repo/scripts/prepare-host-release.sh"
bash -n "$repo/scripts/install-host-gateway.sh"
agent_home=$(getent passwd "$agent_user" | cut -d: -f6)
[[ -n "$agent_home" && -d "$agent_home" && ! -L "$agent_home" ]] || { echo 'Existing dedicated agent home required' >&2; exit 1; }
auth="$agent_home/.ssh/authorized_keys"
[[ -f "$auth" && ! -L "$auth" && ! -L "$agent_home/.ssh" ]] || { echo 'Existing authorized_keys required' >&2; exit 1; }
command -v runuser >/dev/null || { echo 'runuser required' >&2; exit 1; }
runuser -u "$agent_user" -- true || { echo 'Cannot verify SSH account permissions' >&2; exit 1; }
parent=$(dirname -- "$agent_home")
while [[ "$parent" != / ]]; do
  if runuser -u "$agent_user" -- test -w "$parent"; then
    echo "Agent can replace SSH home through: $parent" >&2; exit 1
  fi
  parent=$(dirname -- "$parent")
done
mapfile -t entries < <(grep -Ev '^[[:space:]]*(#|$)' "$auth" || true)
[[ ${#entries[@]} -eq 1 ]] || { echo 'Expected exactly one active authorized key' >&2; exit 1; }
read -r -a key_fields <<< "${entries[0]}"
[[ ${#key_fields[@]} -eq 4 && "${key_fields[1]}" == ssh-ed25519 && "${key_fields[3]}" == "$key_comment" && "${key_fields[2]}" =~ ^[A-Za-z0-9+/]+={0,2}$ ]] || { echo 'Expected single ed25519 key/comment not found' >&2; exit 1; }
[[ "${key_fields[0]}" == 'restrict,command="/usr/bin/hostname"' ]] || { echo 'Expected hostname-only key; review manually' >&2; exit 1; }
key="${key_fields[1]} ${key_fields[2]} ${key_fields[3]}"
key_info=$(printf '%s\n' "$key" | ssh-keygen -lf - -E sha256) || { echo 'Invalid SSH key' >&2; exit 1; }
[[ "$(awk '{print $2}' <<< "$key_info")" == "$key_fingerprint" ]] || { echo 'SSH key fingerprint mismatch' >&2; exit 1; }
command -v visudo >/dev/null || { echo 'visudo required' >&2; exit 1; }
command -v sudo >/dev/null || { echo 'sudo required' >&2; exit 1; }
# The independently installed root-owned verifier checks the approved release
# and every privileged destination before any installed executable changes.
guard=/usr/local/libexec/signal-desk/release-guard.py
[[ -f "$guard" && ! -L "$guard" ]] || { echo 'Trusted release guard missing' >&2; exit 1; }
cmp -s -- "$guard" "$repo/scripts/host_release_guard.py" || { echo 'Release guard differs from reviewed copy' >&2; exit 1; }
/usr/bin/python3 "$guard" verify --settings "$settings" --auth-path "$auth" >/dev/null
install -d -o root -g root -m 755 /usr/local/libexec/signal-desk /etc/signal-desk
install -o root -g root -m 755 "$repo/scripts/host-gateway.sh" /usr/local/libexec/signal-desk/host-gateway
install -o root -g root -m 755 "$repo/scripts/host-gateway-dispatch.sh" /usr/local/libexec/signal-desk/dispatch
conf_tmp=$(mktemp /etc/signal-desk/.host-gateway.XXXXXXXX)
sudo_tmp=$(mktemp /etc/sudoers.d/.signal-desk.XXXXXXXX)
trap 'rm -f -- "$conf_tmp" "$sudo_tmp" "${auth_tmp:-}"' EXIT
install -o root -g root -m 600 "$settings" "$conf_tmp"
# Check the installed verifier against the root-approved checkout before auth.
/usr/bin/python3 /usr/local/libexec/signal-desk/release-guard.py verify --settings "$conf_tmp" >/dev/null
printf '%s\n' "Defaults:$agent_user env_reset, secure_path=\"/usr/sbin:/usr/bin:/sbin:/bin\"" \
  "$agent_user ALL=(root) NOPASSWD: /usr/local/libexec/signal-desk/host-gateway status, /usr/local/libexec/signal-desk/host-gateway validate, /usr/local/libexec/signal-desk/host-gateway deploy" > "$sudo_tmp"
chown root:root "$sudo_tmp"; chmod 440 "$sudo_tmp"
visudo -cf "$sudo_tmp" >/dev/null
# Close writable SSH paths before replacing the forced key; parent ancestry
# was checked when the root-approved release was prepared.
chown root:root "$agent_home" "$agent_home/.ssh" "$auth"
chmod 755 "$agent_home"; chmod 755 "$agent_home/.ssh"; chmod 644 "$auth"
auth_tmp=$(mktemp "$agent_home/.ssh/.authorized_keys.XXXXXXXX")
printf 'restrict,command="/usr/local/libexec/signal-desk/dispatch" %s\n' "$key" > "$auth_tmp"
chown root:root "$auth_tmp"; chmod 644 "$auth_tmp"
mv -f -- "$conf_tmp" /etc/signal-desk/host-gateway.json
mv -f -- "$auth_tmp" "$auth"
# Publish privilege only after the forced key is effective.
mv -f -- "$sudo_tmp" /etc/sudoers.d/signal-desk-host-gateway
echo 'HOST_GATEWAY_READY: status validate deploy (application not deployed)'
