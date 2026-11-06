# REVIEW ONLY until merged/staged and separately approved by VPS root operator.
# One credential-free acceptance attempt; NEVER run from the development checkout.
(
set -euo pipefail
umask 077
SOURCE=/srv/signal-desk-once-source
REVIEW=/srv/signal-desk-once-review
RUNNER=/srv/signal-desk-once-runner
QUEUE=/srv/signal-desk-once-queue
AUTH=/srv/signal-desk-once-auth
CONTEXT=/srv/signal-desk-once-context
HOME_DIR=/srv/signal-desk-once-home
IMAGE='sha256:0ea63377bd672cb76de6a8510aaaef619fe2a045558b771656c072ef527c344f'
PIN='00acd27132b68264ee2ab1692d3024f09c640c6d'
PROJECT='signal-desk-bridge-once'
NET='signal-desk-bridge-once_worker_isolated'
LABEL='org.signal-desk.issue41.fixture'
[[ $(id -u) == 0 ]] || { printf 'STOP: root host terminal required\n' >&2; exit 2; }
[[ -z ${DOCKER_HOST:-} && -z ${DOCKER_CONTEXT:-} ]] || { printf 'STOP: non-default Docker endpoint; verify daemon separately\n' >&2; exit 2; }
[[ ${REVIEW_MERGE:-} =~ ^[0-9a-f]{40}$ ]] || { printf 'STOP: operator must supply reviewed merged full SHA\n' >&2; exit 2; }
export COMPOSE_PROJECT_NAME="$PROJECT"
read -r -p 'Verified existing host source of approved test venv: ' VENV_HOST </dev/tty
read -r -p 'Approved private host canary IPv4:port (>1023, not application/data): ' HOST_CANARY </dev/tty
HOST_IP=${HOST_CANARY%:*}; HOST_PORT=${HOST_CANARY##*:}
python3 -I -B -c 'import ipaddress,sys; ip=ipaddress.ip_address(sys.argv[1]); p=int(sys.argv[2]); allowed=[ipaddress.ip_network(x) for x in ("10.0.0.0/8","172.16.0.0/12","192.168.0.0/16")]; assert any(ip in n for n in allowed) and 1024<=p<=65535' "$HOST_IP" "$HOST_PORT"
[[ "$VENV_HOST" == /* && -d "$VENV_HOST" && ! -L "$VENV_HOST" && -f "$VENV_HOST/pyvenv.cfg" && -L "$VENV_HOST/bin/python" ]]
[[ "$(timeout 10s docker image inspect --format '{{.Id}}' "$IMAGE")" == "$IMAGE" ]]
[[ "$(stat -c '%u:%g:%a' "$SOURCE")" == 0:0:700 ]]
[[ "$(git --git-dir="$SOURCE" cat-file -t "$REVIEW_MERGE")" == commit ]]
[[ "$(git -c safe.directory="$RUNNER" -C "$RUNNER" rev-parse HEAD)" == "$PIN" && -z "$(git -c safe.directory="$RUNNER" -C "$RUNNER" status --porcelain=v1 --untracked-files=all)" ]]
for d in "$QUEUE" "$AUTH" "$CONTEXT" "$HOME_DIR"; do
  [[ "$(stat -c '%u:%g:%a' "$d")" == 10000:10000:700 ]]
  [[ -z "$(find "$d" -mindepth 1 -maxdepth 1 -print -quit)" ]]
done
# Operator independently stages and verifies every merged blob BEFORE invoking this script.
# Recheck all directly consumed helpers against the separately protected merged object store.
for file in compose.yml connect_proxy.py network_acceptance.py network_preflight.py network_resources.py canary_lifecycle.sh host_canary.py worker_firewall.sh network_acceptance_host.sh; do
  [[ "$(timeout 10s git --git-dir="$SOURCE" show "$REVIEW_MERGE:ops/bridge_one_shot/$file" | sha256sum | cut -d' ' -f1)" == "$(sha256sum "$REVIEW/$file" | cut -d' ' -f1)" ]] || {
    printf 'STOP: staged helper differs from merged blob: %s\n' "$file" >&2; exit 2;
  }
done
source "$REVIEW/canary_lifecycle.sh"
export HERMES_IMAGE_REF="$IMAGE" HERMES_UID=10000 HERMES_GID=10000
export BRIDGE_REVIEW_HOST="$REVIEW" BRIDGE_RUNNER_HOST="$RUNNER" BRIDGE_QUEUE_HOST="$QUEUE"
export BRIDGE_AUTH_DIR_HOST="$AUTH" BRIDGE_CONTEXT_DIR_HOST="$CONTEXT"
export BRIDGE_HOME_HOST="$HOME_DIR" BRIDGE_VENV_HOST="$VENV_HOST" BRIDGE_ONCE_APPROVED=no
compose() { timeout 45s docker compose --env-file /dev/null -f "$REVIEW/compose.yml" --profile execution "$@"; }
compose config -q
# No Compose resources, interfaces or dedicated firewall chains may predate this attempt.
[[ -z "$(timeout 10s docker ps -aq --no-trunc --filter label=com.docker.compose.project="$PROJECT")" ]]
[[ -z "$(timeout 10s docker network ls --no-trunc -q --filter label=com.docker.compose.project="$PROJECT")" ]]
! ip link show br-sd-once >/dev/null 2>&1
! ip link show br-sd-uplink >/dev/null 2>&1
timeout 8s iptables -S INPUT >/dev/null
timeout 8s iptables -S DOCKER-USER >/dev/null
! iptables -S SD_ONCE_IN >/dev/null 2>&1
! iptables -S SD_ONCE_FWD >/dev/null 2>&1
BASELINE="$(timeout 10s docker ps -q --no-trunc | sort)"
NETWORK_BASELINE="$(timeout 10s docker network ls --no-trunc -q | sort)"
timeout 30s python3 -I -B "$REVIEW/network_preflight.py"
read -r TOKEN </proc/sys/kernel/random/uuid
FIX_NAME="sd-issue41-net-$TOKEN"
CANARY_OWNER_PID='' CANARY_READ_FD='' CANARY_WRITE_FD=''
PROXY_STARTED=0; FW_ATTEMPTED=0; FIX_ATTEMPTED=0; FIXTURE_PASSED=0; COUNTERS_OBSERVED=0
# Cleanup on success/failure; never stop/remove an unidentified resource or flush global rules.
cleanup() {
  local prior=$? residual=0 fid fmeta pid pmeta peers current role ids network_id interface
  trap - EXIT INT TERM
  set +e
  if [[ "$FIX_ATTEMPTED" == 1 ]]; then
    fmeta="$(timeout 10s docker container inspect --format '{{.Id}}|{{.Image}}|{{index .Config.Labels "org.signal-desk.issue41.fixture"}}' "$FIX_NAME" 2>/dev/null)"
    if [[ -n "$fmeta" ]]; then
      IFS='|' read -r fid current peers <<< "$fmeta"
      if [[ -n "$fid" && "$current" == "$IMAGE" && "$peers" == "$TOKEN" ]]; then
        timeout 15s docker rm -f "$fid" >/dev/null || residual=1
      else printf 'CLEANUP REFUSED: fixture identity mismatch\n' >&2; residual=1; fi
    else
      local listed
      listed="$(timeout 10s docker ps -aq --no-trunc --filter name="^${FIX_NAME}$" 2>/dev/null)"
      if [[ $? != 0 || -n "$listed" ]]; then
        printf 'CLEANUP UNKNOWN: fixture inspect/list failed or name remains\n' >&2; residual=1
      fi
    fi
  fi
  canary_stop || residual=1
  if [[ "$FW_ATTEMPTED" == 1 ]]; then
    if timeout 15s bash "$REVIEW/worker_firewall.sh" status >/dev/null 2>&1; then
      AUTODEV_FIREWALL_APPROVED=yes-for-reviewed-network timeout 25s bash "$REVIEW/worker_firewall.sh" rollback || residual=1
      if iptables -S SD_ONCE_IN >/dev/null 2>&1 || iptables -S SD_ONCE_FWD >/dev/null 2>&1; then residual=1; fi
    else
      printf 'CLEANUP REFUSED: firewall not in reviewed exact state; inspect partial rules manually\n' >&2
      residual=1
    fi
  fi
  # If firewall/fixture cleanup was uncertain, leave proxy/network for root reconciliation.
  if [[ "$residual" == 0 && "$PROXY_STARTED" == 1 ]]; then
    pid="$(timeout 10s docker ps -aq --no-trunc --filter label=com.docker.compose.project="$PROJECT" --filter label=com.docker.compose.service=connect-proxy)"
    if [[ $? != 0 ]]; then
      residual=1
    elif [[ -z "$pid" ]]; then
      printf 'ZERO_PROXY: startup created no proxy container; checking both owned networks for empty cleanup\n'
    elif [[ $(wc -w <<<"$pid") == 1 ]]; then
      pmeta="$(timeout 10s docker inspect --type container --format '{{.Image}}|{{index .Config.Labels "com.docker.compose.project"}}|{{index .Config.Labels "com.docker.compose.service"}}' "$pid" 2>/dev/null)"
      if [[ "$pmeta" == "$IMAGE|$PROJECT|connect-proxy" ]]; then
        timeout 15s docker stop --time 5 "$pid" >/dev/null && timeout 15s docker rm "$pid" >/dev/null || residual=1
      else printf 'CLEANUP REFUSED: proxy identity mismatch\n' >&2; residual=1; fi
    else printf 'CLEANUP UNKNOWN: proxy count is not one\n' >&2; residual=1; fi
  fi
  # Network creation may have succeeded before proxy creation failed. Inspect and
  # remove each independently by ID only when labels, subnet, isolation and emptiness match.
  if [[ "$residual" == 0 && "$PROXY_STARTED" == 1 ]]; then
    for role in worker_isolated proxy_uplink; do
      if [[ "$role" == worker_isolated ]]; then interface=br-sd-once; else interface=br-sd-uplink; fi
      ids="$(timeout 10s docker network ls --no-trunc -q --filter label=com.docker.compose.project="$PROJECT" --filter label=com.docker.compose.network="$role")"
      if [[ $? != 0 ]]; then residual=1; continue; fi
      if [[ -z "$ids" ]]; then
        if ip link show "$interface" >/dev/null 2>&1; then residual=1; fi
        continue
      fi
      if [[ $(wc -w <<<"$ids") != 1 ]]; then residual=1; continue; fi
      network_id="$(timeout 10s docker network inspect "$ids" | timeout 10s python3 -I -B "$REVIEW/network_resources.py" --role "$role")"
      if [[ $? != 0 || "$network_id" != "$ids" ]]; then residual=1; continue; fi
      timeout 15s docker network rm "$network_id" >/dev/null || residual=1
    done
  fi
  if [[ "$residual" == 0 ]]; then
    [[ "$(timeout 10s docker ps -q --no-trunc | sort)" == "$BASELINE" ]] || residual=1
    [[ "$(timeout 10s docker network ls --no-trunc -q | sort)" == "$NETWORK_BASELINE" ]] || residual=1
  fi
  if [[ "$residual" == 0 ]]; then
    printf 'CLEANUP VERIFIED: attempt-owned networks absent; existing container and network IDs unchanged\n'
    if [[ "$prior" == 0 && "$FIXTURE_PASSED" == 1 ]]; then
      printf 'CREDENTIAL-FREE NETWORK FIXTURE: PASS; firewall DROP counters observed=%s\n' "$COUNTERS_OBSERVED"
      [[ "$COUNTERS_OBSERVED" == 1 ]] || printf 'Firewall packet path unobserved (isolated routes may reject first); no full host GO\n'
    fi
  else
    printf 'CLEANUP/BASELINE UNCONFIRMED: preserve state for root review; do not run caller\n' >&2
    exit 125
  fi
  exit "$prior"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# Bounded proxy-only startup; explicit target and --no-deps prevent Bridge caller launch.
PROXY_STARTED=1
compose up -d --no-deps --no-recreate --no-build --pull never connect-proxy
PROXY_ID="$(timeout 10s docker ps -q --no-trunc --filter label=com.docker.compose.project="$PROJECT" --filter label=com.docker.compose.service=connect-proxy)"
[[ $(wc -w <<<"$PROXY_ID") == 1 ]]
[[ "$(timeout 10s docker inspect --type container --format '{{.Image}}|{{.State.Running}}' "$PROXY_ID")" == "$IMAGE|true" ]]
[[ "$(timeout 10s docker ps -aq --no-trunc --filter label=com.docker.compose.project="$PROJECT")" == "$PROXY_ID" ]]
# Both attempt-owned networks must contain this proxy and no other peer.
for role in worker_isolated proxy_uplink; do
  ids="$(timeout 10s docker network ls --no-trunc -q --filter label=com.docker.compose.project="$PROJECT" --filter label=com.docker.compose.network="$role")"
  [[ $(wc -w <<<"$ids") == 1 ]]
  [[ "$(timeout 10s docker network inspect "$ids" | timeout 10s python3 -I -B "$REVIEW/network_resources.py" --role "$role" --proxy-id "$PROXY_ID")" == "$ids" ]]
done
FW_ATTEMPTED=1
AUTODEV_FIREWALL_APPROVED=yes-for-reviewed-network timeout 25s bash "$REVIEW/worker_firewall.sh" apply
timeout 15s bash "$REVIEW/worker_firewall.sh" status
first_rule() { timeout 8s iptables -S "$1" | python3 -c 'import sys; print(next((s.strip() for s in sys.stdin if s.startswith("-A ")), "MISSING"))'; }
[[ "$(first_rule INPUT)" == '-A INPUT -s 172.30.50.2/32 -i br-sd-once -j SD_ONCE_IN' || "$(first_rule INPUT)" == '-A INPUT -i br-sd-once -s 172.30.50.2/32 -j SD_ONCE_IN' ]]
[[ "$(first_rule DOCKER-USER)" == '-A DOCKER-USER -s 172.30.50.2/32 -i br-sd-once -j SD_ONCE_FWD' || "$(first_rule DOCKER-USER)" == '-A DOCKER-USER -i br-sd-once -s 172.30.50.2/32 -j SD_ONCE_FWD' ]]
# Record dedicated DROP counters; isolated routing can reject before either chain.
drop_pkts() {
  timeout 8s iptables -v -x -n -L "$1" | python3 -c 'import sys; rows=[s.split() for s in sys.stdin if " DROP " in " "+s+" "]; assert len(rows)==1; print(int(rows[0][0]))'
}
IN_BEFORE=$(drop_pkts SD_ONCE_IN)
FWD_BEFORE=$(drop_pkts SD_ONCE_FWD)
# Owned, bounded host canary. READY is emitted only after this child's bind/listen.
# A preoccupied port emits BIND_FAILED; never probe it as a presumed test listener.
coproc CANARY {
  exec timeout --signal=TERM --kill-after=5s 155s python3 -I -B -u "$REVIEW/host_canary.py" "$HOST_IP" "$HOST_PORT" "$TOKEN"
}
canary_capture || { printf 'NO-GO: canary exited before coprocess metadata snapshot\n' >&2; exit 2; }
CANARY_READY=0
if ! canary_read CANARY_LINE 5; then
  printf 'NO-GO: owned host canary gave no bounded bind/readiness result\n' >&2; exit 2
fi
if [[ "$CANARY_LINE" == BIND_FAILED ]]; then
  printf 'NO-GO: canary bind failed; do not connect to a preoccupied endpoint\n' >&2; exit 2
fi
if [[ "$CANARY_LINE" == "READY $TOKEN" ]] && canary_is_live; then
  # The response, not a generic successful TCP handshake, proves endpoint ownership.
  timeout 5s python3 -I -B -c '
import socket,sys
ip,port,token=sys.argv[1],int(sys.argv[2]),sys.argv[3].encode("ascii")
with socket.create_connection((ip,port),timeout=2) as s:
    s.settimeout(2); s.sendall(token+b"\n")
    assert s.makefile("rb").readline(128)==b"CANARY-OK "+token+b"\n"
print("HOST_CANARY_CHALLENGE_VERIFIED")
' "$HOST_IP" "$HOST_PORT" "$TOKEN"
  if canary_read CANARY_ACK 5 && [[ "$CANARY_ACK" == HOST_CANARY_CHALLENGE_OK ]] && canary_is_live; then
    CANARY_READY=1
  fi
fi
[[ "$CANARY_READY" == 1 ]] || { printf 'NO-GO: owned synthetic host listener did not prove bind/readiness/challenge\n' >&2; exit 2; }
FIX_ATTEMPTED=1
if timeout --signal=TERM --kill-after=5s 110s docker run \
  --pull=never --name "$FIX_NAME" --label "$LABEL=$TOKEN" \
  --network "$NET" --ip 172.30.50.2 --user 10000:10000 \
  --cpus 0.25 --memory 128m --memory-swap 128m --pids-limit 32 \
  --cap-drop ALL --security-opt no-new-privileges --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=16m --log-driver none --restart no \
  --mount "type=bind,source=$REVIEW/network_acceptance.py,target=/opt/network_acceptance.py,readonly" \
  --entrypoint /opt/hermes/.venv/bin/python "$IMAGE" -B /opt/network_acceptance.py \
  --approved-fixture --host-canary "$HOST_CANARY"; then
  printf 'FIXTURE EXIT 0: checking host firewall counters and cleanup\n'
else
  rc=$?; printf 'NO-GO: fixture exit=%s (124=outer timeout)\n' "$rc" >&2; exit "$rc"
fi
canary_is_live || { printf 'NO-GO: owned host canary exited before negative check completed\n' >&2; exit 2; }
IN_AFTER=$(drop_pkts SD_ONCE_IN); FWD_AFTER=$(drop_pkts SD_ONCE_FWD)
if [[ "$IN_AFTER" -gt "$IN_BEFORE" && "$FWD_AFTER" -gt "$FWD_BEFORE" ]]; then
  COUNTERS_OBSERVED=1
else
  printf 'NOTE: scoped DROP counters did not both rise; isolated routes may reject before iptables. Record counts privately; do not claim firewall packet-path acceptance.\n' >&2
fi
FIXTURE_PASSED=1
# EXIT trap removes ONLY verified new fixture, exact scoped rules, proxy and both owned networks.
)