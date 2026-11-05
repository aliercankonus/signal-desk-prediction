#!/usr/bin/env bash
# HOST-ONLY. Never run from the Hermes container. No global flush or service restart.
set -euo pipefail

ACTION="${1:-}"
[[ "$ACTION" == status || "$ACTION" == apply || "$ACTION" == rollback ]] || { echo 'usage: worker_firewall.sh status|apply|rollback' >&2; exit 2; }
ipt() { iptables -w 5 "$@"; }

network_gate() {
  docker info --format '{{.ServerVersion}}' >/dev/null
  local ids
  ids="$(docker network ls -q --filter label=com.docker.compose.project=hermes-autodev-supervisor --filter label=com.docker.compose.network=worker_isolated)"
  [[ "$(wc -w <<<"$ids")" -eq 1 ]] || { echo 'NO-GO: expected one isolated worker network' >&2; exit 2; }
  docker network inspect "$ids" | python3 -c '
import json,sys
n,=json.load(sys.stdin)
assert n["Driver"] == "bridge" and n["Internal"] is True and n["EnableIPv6"] is False
assert n["IPAM"]["Config"][0]["Subnet"] == "172.30.50.0/28"
assert n["Options"].get("com.docker.network.bridge.name") == "br-autodev"
assert n["Options"].get("com.docker.network.bridge.gateway_mode_ipv4") == "isolated"
' || { echo 'NO-GO: unexpected network configuration' >&2; exit 2; }
  ip link show br-autodev >/dev/null
}

rules_check() {
  ipt -C INPUT -i br-autodev -s 172.30.50.2/32 -j AUTODEV_IN
  ipt -C DOCKER-USER -i br-autodev -s 172.30.50.2/32 -j AUTODEV_FWD
  ipt -C AUTODEV_IN -j DROP
  ipt -C AUTODEV_FWD -d 172.30.50.3/32 -p tcp --dport 3128 -j RETURN
  ipt -C AUTODEV_FWD -j DROP
  [[ "$(ipt -S AUTODEV_IN | wc -l)" -eq 2 && "$(ipt -S AUTODEV_FWD | wc -l)" -eq 3 ]] || {
    echo 'NO-GO: unexpected rules in dedicated chains' >&2; return 1;
  }
}

case "$ACTION" in
  status)
    network_gate
    rules_check
    echo 'PASS: scoped worker firewall jumps and chains installed'
    ;;
  apply)
    [[ "${AUTODEV_FIREWALL_APPROVED:-}" == 'yes-for-reviewed-network' ]] || { echo 'explicit host approval required' >&2; exit 2; }
    network_gate
    if ipt -S AUTODEV_IN >/dev/null 2>&1 || ipt -S AUTODEV_FWD >/dev/null 2>&1; then
      rules_check # Existing chains must be exactly ours; never overwrite unknown host rules.
      exit 0
    fi
    ipt -N AUTODEV_IN
    ipt -N AUTODEV_FWD
    ipt -A AUTODEV_IN -j DROP
    ipt -A AUTODEV_FWD -d 172.30.50.3/32 -p tcp --dport 3128 -j RETURN
    ipt -A AUTODEV_FWD -j DROP
    ipt -I INPUT 1 -i br-autodev -s 172.30.50.2/32 -j AUTODEV_IN
    ipt -I DOCKER-USER 1 -i br-autodev -s 172.30.50.2/32 -j AUTODEV_FWD
    rules_check
    ;;
  rollback)
    [[ "${AUTODEV_FIREWALL_APPROVED:-}" == 'yes-for-reviewed-network' ]] || { echo 'explicit host approval required' >&2; exit 2; }
    docker info --format '{{.ServerVersion}}' >/dev/null
    if [[ "$(docker inspect --format '{{.State.Running}}' hermes-autodev-worker 2>/dev/null || true)" == true ]]; then
      echo 'stop only the new worker before firewall rollback' >&2; exit 2
    fi
    # Refuse unknown chain contents; remove only exact jumps and dedicated chains.
    rules_check
    ipt -D DOCKER-USER -i br-autodev -s 172.30.50.2/32 -j AUTODEV_FWD
    ipt -D INPUT -i br-autodev -s 172.30.50.2/32 -j AUTODEV_IN
    ipt -F AUTODEV_FWD
    ipt -X AUTODEV_FWD
    ipt -F AUTODEV_IN
    ipt -X AUTODEV_IN
    ;;
esac
