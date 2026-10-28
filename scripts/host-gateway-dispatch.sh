#!/usr/bin/env bash
# Installed as a root-owned SSH forced command. Never interpret a shell command.
set -euo pipefail
case "${SSH_ORIGINAL_COMMAND-}" in
  status|validate|deploy) operation="$SSH_ORIGINAL_COMMAND" ;;
  *) echo 'Denied: use exactly status, validate or deploy' >&2; exit 2 ;;
esac
exec /usr/bin/sudo -n -- /usr/local/libexec/signal-desk/host-gateway "$operation"
