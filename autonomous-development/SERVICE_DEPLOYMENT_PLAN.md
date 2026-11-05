# Autonomous supervisor/worker network deployment — REVIEW ONLY

**NO-GO until host acceptance and separate activation approval.** No container, Docker network, firewall rule, systemd unit, existing service or credential was changed by this work. The worker is not started. The supervisor remains networkless, read-only and resource bounded. The worker retains isolated `/worker-home`, exact-repo dispatch, shared queue flock, durable `running`/429 pauses, and no Docker socket or host SSH/auth mount.

## Proposed minimal network

- `worker_isolated`: dedicated IPv4 `172.30.50.0/28`, static worker `172.30.50.2`, proxy `172.30.50.3`, `internal: true`, bridge gateway mode `isolated`, IPv6 disabled, interface `br-autodev`. **Do not create it** until `network_preflight.py` returns PASS on the actual Docker host against *all* host IPv4 routes and Docker networks. The three reported Docker networks do not overlap, but host routes were unavailable here.
- `codex-proxy`: unprivileged, no credentials, read-only single-script mount, no published port, binds only `172.30.50.3:3128`; secondary uplink on existing default `bridge` network. The CONNECT-only code accepts exact `auth.openai.com:443` and `chatgpt.com:443`, the installed Hermes defaults (`auth_constants.py`, `auth_codex.py`); it resolves DNS, rejects any non-global answer and connects to the vetted IP. TLS remains end-to-end. It does **not** inspect TLS URL paths, so host allowlisting is narrower than general Internet access but cannot prove that only `/oauth/token`, `/backend-api/codex`, and device-auth paths are used. Review Hermes `HERMES_CODEX_BASE_URL`/model overrides before activation: other endpoints fail closed, not silently widened.
- Worker has **only** the isolated network. HTTP(S)/ALL proxy variables point to `172.30.50.3`. The isolated bridge is the primary network boundary even if a child ignores proxy environment variables. A scoped `INPUT`/`DOCKER-USER` rule set additionally drops traffic sourced from worker `.2` on `br-autodev` except TCP to proxy `.3:3128`; no global flush. Proxy itself can reach public addresses via the default bridge but has no credentials. Proxy compromise, a malicious TLS request to an allowed host, or access to deployment secrets inside an approved repository remain risks; production deployment authority must remain outside worker mounts.
- File `worker_firewall.sh` stages only host commands; `autodev-worker-firewall.service.in` stages persistence after Docker starts. They are **not installed**. Docker's internal isolated network must be independently proven to block the worker from host and other networks, including before the firewall unit runs after reboot. Until that proof, do not set the worker's restart policy live.

## Host acceptance gates — unexecuted

1. In a trusted host terminal, inspect the original Hermes container ID, immutable image ID, start time, runtime UID/GID, true `/opt/data` bind source, available CPU/RAM/PIDs/disk, worker-home mode/ownership and backup persistence. Verify all Compose variable host sources (code, queue, checkpoints, dedicated worker home, config, skills, memories, **single approved nonproduction workspace**) and that the intended image includes the pinned Python. Confirm no existing sidecars/watchers and no protected deployment paths/symlinks in the workspace. Preserve all current queue and checkpoint records.
2. Verify route/subnet exclusivity before Docker creates the network. The script calls `ip -j -4 route show table all`, `docker network ls` and `docker network inspect`, and fails closed if either is unavailable. Review the actual `docker compose --profile execution ... config --format json` in a trusted terminal; it contains host paths but no credential values. Confirm the default bridge/uplink and installed Hermes endpoint overrides; do not extend the proxy allowlist by guessing.
3. After a **separate explicit host approval**, start **proxy only**, which creates the network; verify its exact network options, names, interface and attached containers. Apply the scoped firewall with explicit approval. Never create/start the worker while the network or firewall gate is unknown. A Docker profile is not an authorization mechanism.
4. Before any worker activation, run a disposable **credential-free** fixture at `.2` on the isolated network (not the worker): direct TCP to `1.1.1.1:443`, the actual host gateway/admin addresses, `172.16.0.0/24`, `172.16.1.0/24`, metadata/link-local, production endpoints and Docker TCP API must fail; unauthorized CONNECT hosts, ports, IP literals and DNS rebinding must fail. Proxy CONNECT plus a TLS handshake (no HTTP request or model call) to `auth.openai.com:443` and `chatgpt.com:443` must succeed. Repeat direct negatives after proxy/firewall restart and host reboot; record effective `iptables` and network inspect output. Do not contact production endpoints merely to test denial: use local synthetic listeners on the same routed targets where safe, and inspect host rules for actual destinations.
5. The worker home's isolated Codex login is **not provisioned**. An operator must separately authorize an OAuth flow into that private 0700 home; never copy current Hermes credentials. A synthetic atomic store rotation passed locally, but live refresh and provider reachability are not verified. Do not start the worker or spend model quota as a preflight shortcut.

## Exact operator commands (future approval only; NONE executed here)

Set the host-inspected `HERMES_*` Compose inputs from `compose.supervisor.yml`, and `HERMES_CODE_HOST_PATH` to the **host** path for this directory. Require an authenticated Docker host terminal; do not infer its path from `/opt/data` inside Hermes.

```sh
python3 "$HERMES_CODE_HOST_PATH/network_preflight.py"
docker compose --profile execution -f "$HERMES_CODE_HOST_PATH/compose.supervisor.yml" config -q
# Record original Hermes container ID/start time before any approved action.
# Separately approved network/proxy staging, NOT the worker:
docker compose --profile execution -f "$HERMES_CODE_HOST_PATH/compose.supervisor.yml" up -d --no-deps --no-recreate --pull never codex-proxy
# Inspect worker_isolated: internal=true, isolated gateway, subnet, static proxy IP and no other peers.
AUTODEV_FIREWALL_APPROVED=yes-for-reviewed-network bash "$HERMES_CODE_HOST_PATH/worker_firewall.sh" apply
bash "$HERMES_CODE_HOST_PATH/worker_firewall.sh" status
# Provider-free disposable fixture; never run alongside the worker (it uses .2).
# HOST_CANARY must be an approved synthetic listener IP:port, independently confirmed reachable from the host.
docker run --rm --pull=never --network hermes-autodev-supervisor_worker_isolated \
  --ip 172.30.50.2 --user 65534:65534 --cap-drop ALL --security-opt no-new-privileges \
  --read-only --tmpfs /tmp:rw,nosuid,nodev,size=16m \
  --entrypoint /opt/hermes/.venv/bin/python \
  --mount "type=bind,src=$HERMES_CODE_HOST_PATH/network_acceptance.py,dst=/opt/network_acceptance.py,readonly" \
  "$HERMES_IMAGE_REF" /opt/network_acceptance.py --approved-fixture --host-canary "$HOST_CANARY"
# This performs TLS handshakes only, not Codex inference or OAuth login.
# Install only this new unit after validating the inspected host path (never from this agent):
[[ "$HERMES_CODE_HOST_PATH" =~ ^/[A-Za-z0-9/_-]+$ ]] || exit 2
python3 - "$HERMES_CODE_HOST_PATH" <<'PY' | sudo tee /etc/systemd/system/autodev-worker-firewall.service >/dev/null
from pathlib import Path
import sys
source = Path(sys.argv[1]) / 'autodev-worker-firewall.service.in'
print(source.read_text().replace('@CODE_HOST_PATH@', sys.argv[1]))
PY
sudo chmod 0644 /etc/systemd/system/autodev-worker-firewall.service
sudo systemctl daemon-reload
sudo systemctl enable --now autodev-worker-firewall.service
# Only after the disposable provider-free positive/negative tests, private OAuth provisioning,
# host reboot/restart persistence test and a SEPARATE explicit worker approval:
docker compose --profile execution -f "$HERMES_CODE_HOST_PATH/compose.supervisor.yml" up -d --no-deps --no-recreate --pull never worker
# Observer separately optional, no model calls:
docker compose -f "$HERMES_CODE_HOST_PATH/compose.supervisor.yml" up -d --no-deps --no-recreate --pull never supervisor
```

**Important:** Applying firewall rules manually without installing/enabling the reviewed unit does not make them reboot-persistent. The unit must be reviewed and installed by the host operator; this agent has not done it. The proxy is a non-model service but still needs approval to start. Do not issue the worker command merely because Compose validates.

### Scoped rollback (future host operator only)

```sh
docker compose --profile execution -f "$HERMES_CODE_HOST_PATH/compose.supervisor.yml" stop worker supervisor codex-proxy
docker compose --profile execution -f "$HERMES_CODE_HOST_PATH/compose.supervisor.yml" rm --force worker supervisor codex-proxy
# If installed, after the worker is stopped:
sudo systemctl disable --now autodev-worker-firewall.service
sudo rm /etc/systemd/system/autodev-worker-firewall.service
sudo systemctl daemon-reload
# If the unit was never installed, remove only the manually applied rules instead:
# AUTODEV_FIREWALL_APPROVED=yes-for-reviewed-network bash "$HERMES_CODE_HOST_PATH/worker_firewall.sh" rollback
# Confirm the exact Compose network name and that it has no attached containers:
docker network inspect hermes-autodev-supervisor_worker_isolated --format '{{.Name}} {{len .Containers}}'
docker network rm hermes-autodev-supervisor_worker_isolated
# Never use compose down, down -v, a global iptables flush, or touch the original Hermes/app containers.
```

Stop/inspect any `running` task before later activation. Preserve queue, checkpoints and worker home. Compare original Hermes container ID/start time after any approved operation. Host route check, Docker network creation, firewall persistence, proxy connectivity and reboot recovery remain **UNKNOWN** from this container (no host Docker socket). Existing services have not been altered.
