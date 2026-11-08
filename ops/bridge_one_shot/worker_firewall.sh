#!/usr/bin/env bash
# HOST-ONLY. Never run from the Hermes container. No global flush or service restart.
set -euo pipefail
PATH=/usr/sbin:/sbin:/usr/bin:/bin
export PATH

ACTION="${1:-}"
[[ "$ACTION" == status || "$ACTION" == apply || "$ACTION" == rollback ]] || { echo 'usage: worker_firewall.sh status|apply|rollback' >&2; exit 2; }
for tool in iptables ip docker python3 wc; do
  command -v "$tool" >/dev/null || { echo "NO-GO: required host tool unavailable: $tool" >&2; exit 2; }
done
ipt() { iptables -w 5 "$@"; }

network_gate() {
  docker info --format '{{.ServerVersion}}' >/dev/null
  local ids
  ids="$(docker network ls -q --filter label=com.docker.compose.project=signal-desk-bridge-once --filter label=com.docker.compose.network=worker_isolated)"
  [[ "$(wc -w <<<"$ids")" -eq 1 ]] || { echo 'NO-GO: expected one isolated worker network' >&2; exit 2; }
  docker network inspect "$ids" | python3 -c '
import json,sys
n,=json.load(sys.stdin)
assert n["Driver"] == "bridge" and n["Internal"] is True and n["EnableIPv6"] is False
assert n["IPAM"]["Config"][0]["Subnet"] == "172.30.50.0/28"
assert n["Options"].get("com.docker.network.bridge.name") == "br-sd-once"
assert n["Options"].get("com.docker.network.bridge.gateway_mode_ipv4") == "isolated"
' || { echo 'NO-GO: unexpected network configuration' >&2; exit 2; }
  ip link show br-sd-once >/dev/null
}

rules_check() {
  ipt -C INPUT -i br-sd-once -s 172.30.50.2/32 -j SD_ONCE_IN
  ipt -C DOCKER-USER -i br-sd-once -s 172.30.50.2/32 -j SD_ONCE_FWD
  ipt -C SD_ONCE_IN -j DROP
  ipt -C SD_ONCE_FWD -d 172.30.50.3/32 -p tcp --dport 3128 -j RETURN
  ipt -C SD_ONCE_FWD -j DROP
  [[ "$(ipt -S SD_ONCE_IN | wc -l)" -eq 2 && "$(ipt -S SD_ONCE_FWD | wc -l)" -eq 3 ]] || {
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
    if ipt -S SD_ONCE_IN >/dev/null 2>&1 || ipt -S SD_ONCE_FWD >/dev/null 2>&1; then
      rules_check # Existing chains must be exactly ours; never overwrite unknown host rules.
      exit 0
    fi
    ipt -N SD_ONCE_IN
    ipt -N SD_ONCE_FWD
    ipt -A SD_ONCE_IN -j DROP
    ipt -A SD_ONCE_FWD -d 172.30.50.3/32 -p tcp --dport 3128 -j RETURN
    ipt -A SD_ONCE_FWD -j DROP
    ipt -I INPUT 1 -i br-sd-once -s 172.30.50.2/32 -j SD_ONCE_IN
    ipt -I DOCKER-USER 1 -i br-sd-once -s 172.30.50.2/32 -j SD_ONCE_FWD
    rules_check
    ;;
  rollback)
    [[ "${AUTODEV_FIREWALL_APPROVED:-}" == 'yes-for-reviewed-network' ]] || { echo 'explicit host approval required' >&2; exit 2; }
    docker info --format '{{.ServerVersion}}' >/dev/null
    local_ids="$(docker network ls -q --filter label=com.docker.compose.project=signal-desk-bridge-once --filter label=com.docker.compose.network=worker_isolated)"
    [[ "$(wc -w <<<"$local_ids")" -eq 1 ]] || { echo 'NO-GO: isolated network ambiguous' >&2; exit 2; }
    network_info="$(docker network inspect "$local_ids")"
    active="$(printf '%s' "$network_info" | python3 -c '
import json,sys
n,=json.load(sys.stdin)
print("ACTIVE" if any(c.get("IPv4Address", "").split("/")[0] == "172.30.50.2"
                      for c in n.get("Containers", {}).values()) else "EMPTY")
')"
    if [[ "$active" == ACTIVE ]]; then
        echo 'stop the one-shot task container before firewall rollback' >&2; exit 2
    fi
    # Refuse unknown chain contents; remove only exact jumps and dedicated chains.
    rules_check
    ipt -D DOCKER-USER -i br-sd-once -s 172.30.50.2/32 -j SD_ONCE_FWD
    ipt -D INPUT -i br-sd-once -s 172.30.50.2/32 -j SD_ONCE_IN
    ipt -F SD_ONCE_FWD
    ipt -X SD_ONCE_FWD
    ipt -F SD_ONCE_IN
    ipt -X SD_ONCE_IN
    ;;
esac
