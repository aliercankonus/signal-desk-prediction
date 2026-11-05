# Issue #39: one-shot Bridge environment — review only

**Not activated.** This proposal does not authorize a task issue, queue entry, host network/firewall change, credential provisioning, provider request, or historical retry. It is separate from the legacy `execute_task` worker/observer and has no watcher or restart. The sole effectful caller is `bridge_once.py`, gated by a separately frozen private Task Bridge authorization and an explicit future approval marker. After a block or lost result, inspect queue and Bridge `doctor`/`reconcile` plus GitHub read-only; never rerun the caller.

## Identity and provenance

Recent task commits use `Hermes Agent <hermes-agent@users.noreply.github.com>` for **both** author and committer; PR merge commits use GitHub's distinct identity. Proposed nonsecret values are exactly `user.name=Hermes Agent` and `user.email=hermes-agent@users.noreply.github.com`, subject to manager approval. **Do not set global Git identity.** Git's worktree-specific config would not automatically pass to a new worktree. A repository-local `.git/config` is inherited by worktrees sharing that Git common directory; the inert local fixture verifies both effective identities with `user.useConfigOnly=true`. The earlier linked runner worktree shares `.git/config` with the dirty original checkout, so configuring it would change the original repository's scope. Use a **new independent clone** for the approved runner, not that linked worktree. Pin its detached HEAD to the previously reviewed runner merge `00acd27132b68264ee2ab1692d3024f09c640c6d` even if main advances. The PR proposing this environment changes neither that runner pin nor its tested source. The future Bridge rechecks both identities inside its newly created task worktree before launching Hermes.

The following is an **unexecuted operator preparation example**, not a task run. `RUNNER_HOST` must be a new approved path outside every existing checkout and protected release, with a trusted non-writable ancestor; the clone is a development checkout, not a VPS app release. Its `.git/config` is nonsecret but writable by the task UID, so repository contents/prompt are **not** a sandbox. The values are proposed from existing history, not an assertion of an approved identity.

```sh
set -euo pipefail
PIN=00acd27132b68264ee2ab1692d3024f09c640c6d
RUNNER_HOST='<approved-fresh-runner-host-path>'
test ! -e "$RUNNER_HOST" && test ! -L "$RUNNER_HOST"
git clone --no-hardlinks https://github.com/aliercankonus/signal-desk-prediction.git "$RUNNER_HOST"
test "$(git -C "$RUNNER_HOST" cat-file -t "$PIN")" = commit
git -C "$RUNNER_HOST" checkout --detach "$PIN"
git -C "$RUNNER_HOST" config --local user.name 'Hermes Agent'
git -C "$RUNNER_HOST" config --local user.email 'hermes-agent@users.noreply.github.com'
git -C "$RUNNER_HOST" config --local user.useConfigOnly true
test "$(git -C "$RUNNER_HOST" rev-parse HEAD)" = "$PIN"
test "$(git -C "$RUNNER_HOST" remote get-url origin)" = https://github.com/aliercankonus/signal-desk-prediction.git
test -z "$(git -C "$RUNNER_HOST" status --porcelain=v1 --untracked-files=all)"
git -C "$RUNNER_HOST" -c user.useConfigOnly=true var GIT_AUTHOR_IDENT
git -C "$RUNNER_HOST" -c user.useConfigOnly=true var GIT_COMMITTER_IDENT
# STAGED RUNNER ONLY; do not enqueue or run a child.
```

## Proposed container boundary

`compose.yml` names exactly two **non-restarting** services: one one-shot Bridge caller and one credential-free CONNECT proxy. Both use the **same immutable ID of the existing inspected Hermes image** (`HERMES_IMAGE_REF=sha256:<host-observed-64-hex-image-ID>`, not a mutable tag or guessed digest) and the host-inspected non-root UID/GID for the caller. Exact image ID, executable path `/opt/hermes/.venv/bin/python`, installed `hermes`/`git`/certificates, mount source paths and runtime UID **remain unverified on the Docker host**; reject a missing or incompatible image instead of substituting one. No Docker socket, host SSH key, deployment checkout, data volume, app config, legacy queue or broad current home is mounted.

| Mount into caller | Host input and policy |
| --- | --- |
| `/workspace/runner` (rw) | Fresh runner clone; required for Bridge-created task branch/worktree under its private state, and its shared Git metadata. Must contain no `.env`/deployment secrets. |
| `/state/queue` (rw) | Fresh dedicated owner-private `0700` queue with trusted ancestors; per-entry Bridge state and worktrees live here. Never the legacy Worker queue. |
| `/private/auth`, `/private/context` (ro) | **Separate** owner-private `0700` host directories, each containing only its separately reviewed `0600` JSON file. Context pins runner SHA, requirements digest, Python/pytest versions and the container-visible interpreter path. |
| `/worker-home` (rw) | Dedicated owner-private `0700` Hermes home with minimal approved `config.yaml`, isolated provider OAuth store with refresh writes, and Git credential helper state. Do not bind/copy current Hermes home or mount a secret read-only if refresh rotates it. |
| `/opt/data/signal-desk-tooling/venvs/issue26-recovery-python314-20261030` (ro) | Host-inspected existing private Python 3.14.9/pytest 8.3.3 venv; verify symlink target interpreter and imported packages work **inside this image**; no install or fallback. |
| `/opt/bridge-once.py` (ro) | Exact reviewed helper byte from a protected staged review bundle. Proxy gets only its own reviewed `connect_proxy.py` (ro), no home/auth/worktree. |

Caller: read-only root filesystem, `64m` tmpfs, dropped capabilities, no-new-privileges, 1 CPU, 1536 MiB, 128 PIDs, 30s stop grace, 5 MiB × 2 log rotation, no ports, restart `no`. Proxy: same root/capability restrictions, 0.25 CPU, 128 MiB, 32 PIDs, restart `no`. Each proxy tunnel has at most 64 KiB of queued application bytes **per direction**, pauses reads at that limit, preserves partial writes and drains both half-closes; idle and overall deadlines are 180s and 3900s. HTTP 403 is sent only before CONNECT establishment, never inside TLS tunnel bytes. These are relay-local bounds, not host-wide byte or filesystem quotas. The Bridge's installed Hermes command is bounded to 12 turns/600s with a 630s process limit; no claim that this bounds all host filesystem usage or global quota. The isolated Docker network is `172.30.50.0/28`, caller `.2`, proxy `.3:3128`, internal isolated IPv4 bridge `br-sd-once`, no IPv6; proxy alone also joins the existing external `bridge` uplink. Host `INPUT`/`DOCKER-USER` rules deny direct caller traffic other than `.3:3128`. **Only** TLS CONNECT 443 to `github.com` (Git clone/fetch/push), `api.github.com` (issue/PR/check REST), `auth.openai.com`, and `chatgpt.com` (installed Codex auth/inference defaults) is allowed at proxy. TLS remains end-to-end. This host allowlist is not an HTTP method/path restriction: the GitHub credential still permits whatever its scope allows. The proxy's uplink shares the existing default bridge; a compromised proxy may access other peers despite its credential-free design, so inspect that bridge's peers and threat model before approval. Do not expand hosts on a failed request without review.

Git uses `HTTPS_PROXY` and `GIT_CONFIG_GLOBAL=/worker-home/gitconfig`; `gitconfig.example` is the nonsecret template for a **separate** GitHub-only `credential.helper=store --file /worker-home/git-credentials`. The operator provisions a repo-scoped, expiring token into `0600` state without echoing it or copying the broad current credential helper; it needs Contents read/write, Pull requests read/write, Issues read/write, Checks/Actions read as applicable to the reviewed REST adapter. Provider OAuth login is provisioned separately into this isolated home; its refresh file must be writable by the caller UID. No token, OAuth exchange, GitHub write, or model request is performed by this proposal. A successful credential-free TLS handshake only proves routing, not privileges/quota. Recheck the installed Hermes provider endpoints/config without printing secrets; if it needs other hosts, stop.

## Exact future host gates and operator commands — **none executed**

Run in an authenticated host terminal, *not* via the restricted VPS application SSH gateway. Before even staging, operator supplies and privately records `EXISTING_HERMES_CONTAINER`, approved host paths for every `BRIDGE_*_HOST` variable in Compose, host UID/GID, image ID, route/subnet inventory, mount identities, storage/CPU/RAM/PID headroom, no competing worker, and separate reviewed issue/body digest/branch/start. Stage this PR's **merged** helper files as immutable reviewed bytes in a root-protected bundle outside agent mounts; independently compare each staged SHA-256 to its merged-commit blob before running Python or shell. Never stage from a mutable development branch or replace the reviewed runner code with this proposal branch.

**Read-only preflight (after paths and staged bytes are independently checked):**

```sh
set -euo pipefail
REVIEW='<root-protected-staged-bundle>'
EXISTING_HERMES_CONTAINER='<operator-verified-container-id>'
export HERMES_IMAGE_REF="$(docker inspect -f '{{.Image}}' "$EXISTING_HERMES_CONTAINER")"
export HERMES_UID='<inspected-nonroot-uid>' HERMES_GID='<inspected-nonroot-gid>'
export BRIDGE_RUNNER_HOST='<approved-fresh-runner-host-path>'
export BRIDGE_QUEUE_HOST='<approved-fresh-private-queue-host-path>'
export BRIDGE_AUTH_DIR_HOST='<separate-private-auth-dir>'
export BRIDGE_CONTEXT_DIR_HOST='<separate-private-context-dir>'
export BRIDGE_HOME_HOST='<isolated-private-home-dir>'
export BRIDGE_VENV_HOST='<host-source-of-approved-private-venv>'
export BRIDGE_REVIEW_HOST="$REVIEW"
export BRIDGE_ONCE_APPROVED=no
test "$(git -C "$BRIDGE_RUNNER_HOST" rev-parse HEAD)" = 00acd27132b68264ee2ab1692d3024f09c640c6d
test -z "$(git -C "$BRIDGE_RUNNER_HOST" status --porcelain=v1 --untracked-files=all)"
test "$(stat -c %a "$BRIDGE_QUEUE_HOST")" = 700
for d in "$BRIDGE_AUTH_DIR_HOST" "$BRIDGE_CONTEXT_DIR_HOST" "$BRIDGE_HOME_HOST"; do test "$(stat -c %a "$d")" = 700; done
test "$(stat -c %a "$BRIDGE_AUTH_DIR_HOST/authorization.json")" = 600
test "$(stat -c %a "$BRIDGE_CONTEXT_DIR_HOST/context.json")" = 600
python3 "$REVIEW/network_preflight.py"
docker compose -f "$REVIEW/compose.yml" --profile execution config -q
bash -n "$REVIEW/worker_firewall.sh"
python3 -B -c 'import ast,sys; [ast.parse(open(p, encoding="utf-8").read()) for p in sys.argv[1:]]' \
  "$REVIEW/connect_proxy.py" "$REVIEW/bridge_once.py" "$REVIEW/network_acceptance.py"
# READ-ONLY/PREFLIGHT ONLY: no network, proxy, firewall or task started.
```

`stat` alone does not validate ancestry, mount isolation, symlinks, image content or host firewall; those require separate trusted host inspection. The static Compose check does not prove runtime accessibility. The commands above require a host daemon only for `docker inspect` and the route preflight; they are not executable from this container.

**Separate host-network authorization/acceptance, never the task itself:** after a separate approval, start **proxy only** (`docker compose -f "$REVIEW/compose.yml" --profile execution up -d --no-deps --no-recreate connect-proxy`), inspect the exact network/options and attached peers, then apply only the scoped firewall with `AUTODEV_FIREWALL_APPROVED=yes-for-reviewed-network bash "$REVIEW/worker_firewall.sh" apply` and verify `... status`. Use a credential-free disposable fixture on `.2` (not the Bridge caller) with the same immutable image, no mounts except the reviewed acceptance helper, read-only root, non-root UID, dropped caps, no-new-privileges, finite CPU/RAM/PIDs, no restart and a reviewed host synthetic listener:

```sh
# ONLY after separately approved proxy/network/firewall staging; no credentials/model calls.
HOST_CANARY='<approved-synthetic-listener-ip:port>'
docker run --rm --pull=never --network signal-desk-bridge-once_worker_isolated \
  --ip 172.30.50.2 --user "$HERMES_UID:$HERMES_GID" --cpus 0.25 --memory 128m --pids-limit 32 \
  --cap-drop ALL --security-opt no-new-privileges --read-only --tmpfs /tmp:rw,nosuid,nodev,size=16m \
  --entrypoint /opt/hermes/.venv/bin/python \
  --mount "type=bind,src=$REVIEW/network_acceptance.py,dst=/opt/network_acceptance.py,readonly" \
  "$HERMES_IMAGE_REF" -B /opt/network_acceptance.py --approved-fixture --host-canary "$HOST_CANARY"
# Compare host-side canary success, denied direct paths, proxy allow/deny, effective firewall counters;
# inspect no competing peer. Then stop/remove only this fixture (docker run --rm does so).
```

The fixture's TLS handshakes to allowed hosts send no HTTP/model request; denial to arbitrary closed ports alone is inconclusive. For this **non-restarting one-shot** design, firewall persistence across reboot is not claimed or required for automatic restart: a reboot/interruption leaves a claimed `running` task ambiguous and requires manual reconciliation; **do not** restart it. Re-run host preflight/negative tests before a separately authorized future attempt; never start the caller while isolation is unproven.

**Container-visible, provider-free preflight (future separate approval only):** after the disposable fixture exits and isolated credentials are provisioned by the operator, run this read-only container command. It does **not** invoke `bridge_once.py`, enqueue or call Hermes chat; the subsequent child-terminal check remains a separate runtime gate.

```sh
# No model request, task claim, Git write, or PR POST.
docker compose -f "$REVIEW/compose.yml" --profile execution run --rm --no-deps \
  --entrypoint /bin/sh bridge-once -ec '
set -eu
cd /workspace/runner
PY=/opt/data/signal-desk-tooling/venvs/issue26-recovery-python314-20261030/bin/python
test -x "$PY"
"$PY" -I -B -c "import sys,pytest; assert sys.version_info[:3] == (3,14,9); assert pytest.__version__ == \"8.3.3\""
"$PY" -I -B -m pip check
hermes chat --help >/dev/null
test "$(hermes config get terminal.backend)" = local
git -c user.useConfigOnly=true var GIT_AUTHOR_IDENT >/dev/null
git -c user.useConfigOnly=true var GIT_COMMITTER_IDENT >/dev/null
git ls-remote --exit-code origin refs/heads/main >/dev/null
"$PY" -I -B -c "import sys;sys.path.insert(0,\"/workspace/runner/src\");from signal_desk.task_bridge.adapters import GitHubREST;from signal_desk.task_bridge.bridge import Policy;p=Policy(repo=\"aliercankonus/signal-desk-prediction\",issue=39,body_digest=\"a\"*64,base=\"00acd27132b68264ee2ab1692d3024f09c640c6d\",branch=\"review-only\");assert GitHubREST(p)._request(\"GET\",\"/user\").get(\"login\") == \"aliercankonus\""
'
# READ-ONLY CONTAINER PREFLIGHT ONLY; no task invocation.
```

**Separate one-attempt authorization only (NOT executed here):** freeze a *new* issue's exact UTF-8 digest and unused branch, approve the private auth/context, GitHub token/permissions and provider home, and verify its specific authority/context before setting `BRIDGE_ONCE_APPROVED=yes-for-one-frozen-task` in that trusted operator shell; then one `docker compose -f "$REVIEW/compose.yml" --profile execution up --no-deps --no-recreate --abort-on-container-exit --exit-code-from bridge-once bridge-once` **once**. This command is intentionally separate from the staging blocks and is not authorization now. On any exit, preserve the queue/Bridge journal and task worktree; inspect exact remote branch/PR/head/CI and read-only Bridge doctor/reconcile. Never run it again to resolve ambiguity; acknowledgment does not authorize retry. Stop/remove only the new proxy/container/network/rules after evidence is preserved and a separately reviewed rollback. No original service or application release is touched.

**Verified locally:** Git history identity convention; independent Git fixture inheritance; installed bounded Hermes CLI, local backend, Python 3.14.9/pytest 8.3.3 and requirements digest `58f90369318da1e7ab651447080f06bb80c361a4a0109d79eca4762aba8bf97d`; development-container GitHub read access; Compose static validation and inert tests when run. **Unknown on host:** immutable image ID and contents, actual mount sources/ancestry, auth scope/OAuth refresh, subnet exclusivity, firewall effectiveness, resource headroom, negative network tests, GitHub write permission, provider reachability/quota. No claim of host GO or unattended readiness.
