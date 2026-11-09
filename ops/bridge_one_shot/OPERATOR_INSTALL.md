# Issue #41: one dormant root entry — staging and NO-GO gates

**Repository review artifact, not host approval or an installation receipt.** The concrete later staging input generator is [`operator_bootstrap.py`](operator_bootstrap.py), with its nonsecret schema and handoff limits in [`BOOTSTRAP_HANDOFF.md`](BOOTSTRAP_HANDOFF.md). Its `--stage` is not the runtime adapter's `--execute`. The proposed command adapter is `operator_host.py`, and `root_signer.py` is the *root-only* signer it calls. Neither is mounted in the worker. The root entry starts only a proxy and a sleeping isolated inbox worker, never the older direct `bridge_once_candidate.py`; after a fresh manager App instruction and signed grant, only `Inbox.tick → production_executor → BridgeQueue.enqueue → dispatch_one → Bridge.once` may claim #43. No timer or workflow is installed. An empty poll makes no agent/model call.

This adapter can be reviewed/tested before host facts exist. **NO-GO** until an operator independently proves (a) the manager alone can invoke the observed GitHub App route, not merely that App ID 1144995 appears; (b) the actual worker has no path to the root source, key, policy, root token, broad preparation credential or manager connector, and cannot change the root command or its private plan; (c) image ID, UID:GID, existing-container mounts/permissions, networking/firewall and dedicated GitHub credential/refreshable home are inspected on the real host; (d) the root has an independently approved authenticated issue #41 post-cleanup GET/POST route; (e) the immutable merged artifact set and future one-shot authorization are separately approved. A flag, source hash, signed grant, green test or Compose profile proves none of these. If any proof is missing, keep this code staged and **do not invoke `--execute`**.

## Exact inputs to provision *later*, privately and once

1. Root-only protected Git object store `source` containing the **reviewed merged commit**, new `0700` bundle and journal parent outside every worker mount/old release/agent bind. Stage only the eleven files enumerated in `operator_artifacts.json`, then generate the root-only `merged-byte-manifest.json` from the **merged Git blobs**, not a PR-head/branch tip. Two individually mounted worker/proxy helpers (`worker_probe.py`, `connect_proxy.py`) must be root-owned `0444` inside that otherwise root-private bundle; the signer, root host code and independent `bridge_readback.py` verifier remain `0600` and are never mounted. Host command lookup uses a fixed root-controlled `/usr/sbin:/sbin:/usr/bin:/bin` PATH and validates administrative executables before effects. Do not stage from a writable checkout. The unmodified host runner remains `00acd27132b68264ee2ab1692d3024f09c640c6d`; use a *separate*, clean, immutable runner clone at `e84021a786004456a12de9e25eae50d191da6cf1` with effective Git author/committer and the reviewed private Python/pytest context. An operator must read back every staged SHA and exact file set.
2. Root-only `0600` signer Ed25519 private PEM, its public PEM, a **distinct narrowly scoped root GitHub token file** for exact issue GET/comment POST/report GET **and read-only branch/PR/compare/check-runs/workflow/status GETs**, and `signer_policy`, and a **shared root-only 0700 `signer_state_root` fixed by code to `/var/lib/signal-desk/issue41-signer-claims`** outside every attempt journal and worker mount. Provision this path only in a later approved operator step; changing the plan to another path fails closed. The shared directory retains comment-ID claims across attempts; an unresolved sign/POST cannot be retried by choosing a new attempt ID. The root policy's exact fields are `repo`, `task_issue` (=43), `body_digest` (frozen #43 UTF-8 body), `authority_identity` (SHA-256 identity of the private Bridge Policy), `runner_commit`, `start` (future exact UTC enrollment timestamp), `cursors` (`{"41":latest-id,"45":latest-id}`), and `app_id` (=1144995). Capture cursors independently at enrollment time; if either changes before `Inbox.enroll`, fail closed and create **a new reviewed attempt**, not a cursor reset. The key/token/policy/source and root attempt journal are not worker mounts. Never place token/key values, auth stores or private plan in Git, public issue, environment variables or command arguments.
3. Dedicated worker UID:GID, verified image ID, separate private state parent containing an *empty* `queue`, separate `auth`, `context`, refreshable `home`, approved venv and `inbox` mounts. The worker authorization must be `0600`, pin issue #43, body digest, runner/task-start commit `e84021a786004456a12de9e25eae50d191da6cf1` and branch `issue43-one-shot-review-note`. The execution context and `inbox/enrollment.json` use the exact schema in `ops/github_inbox/BOOTSTRAP_REVIEW.md`; the public PEM and its SHA must match the root public PEM. The queue is new and empty; inbox state **does not yet exist**. Existing queue/journals, services, credentials, data and release directories are untouched.
4. Root-owned `0600` operator plan JSON (`operator_host.Plan` fields exactly): `attempt` (new `a-z[0-9a-z-]`, length 6–64), `bundle`, `source`, `merge` (reviewed full merge SHA), `image` (`sha256:` + 64 hex), `uid`, `gid`, `runner`, `state`, `auth`, `context`, `home`, `venv`, `inbox`, `signer_token`, `signer_key`, `signer_public`, `signer_policy`, `signer_state_root`, `overall_seconds` (600–7200; at least 420 seconds reserved for bounded read-only reconciliation, exact cleanup and report) and `journal_parent`. Every path is an operator-verified **absolute host path**; no value is inferred from the development machine. The actual worker paths are fixed *inside* Compose. Keep this plan out of the worker, Git and shared Hermes profile.

## Reference/manual merged-byte staging block — superseded by bootstrap entry; **not executed in this PR**

The block below records the earlier reviewed manual staging recipe, **not a second step to run after `operator_bootstrap.py --stage`**. The new bootstrap stages the same exact bundle and adds the private plan/authority/context/enrollment assembly. Never run both against the same attempt. Only after the above root/source/mount exclusions have been reviewed, and after independently verifying the manager-approved PR merge object and `main` ancestry, the operator can adapt the following block at the root terminal. It does **not** start a container, signer, login, timer or task. It refuses an existing destination and leaves a partial stage for manual reconciliation. Prompts are private; do not paste their answers into an issue.

```sh
set -euo pipefail
umask 077
unset BASH_ENV ENV PYTHONPATH PYTHONHOME GIT_CONFIG_GLOBAL GIT_CONFIG_SYSTEM
read -r -p 'Root-owned protected bare Git object store: ' SOURCE </dev/tty
read -r -p 'Approved full merge commit SHA: ' MERGE </dev/tty
read -r -p 'Fresh root-only bundle path (must not exist): ' BUNDLE </dev/tty
read -r -p 'Reviewed worker/agent/release mount roots, comma-separated absolute paths: ' EXCLUDED </dev/tty
python3 -I -B - "$SOURCE" "$MERGE" "$BUNDLE" "$EXCLUDED" <<'PY'
import hashlib, json, os, pathlib, re, stat, subprocess, sys
source, merge, bundle, excluded = sys.argv[1:]
if not re.fullmatch(r'[0-9a-f]{40}', merge): raise SystemExit('STOP: merge pin')
source, bundle = pathlib.Path(source), pathlib.Path(bundle)
mounts = [pathlib.Path(x) for x in excluded.split(',')]
if not mounts or not all(x.is_absolute() and '..' not in x.parts and x.exists() for x in mounts):
    raise SystemExit('STOP: reviewed exclusion roots required')
def trusted(path):
    for part in (path, *path.parents):
        info = part.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise SystemExit('STOP: root ancestry/owner/mode')
if not source.is_absolute() or not bundle.is_absolute() or '..' in bundle.parts:
    raise SystemExit('STOP: absolute protected paths required')
trusted(source); trusted(bundle.parent)
if bundle.exists() or bundle.is_symlink(): raise SystemExit('STOP: bundle exists')
if any(bundle == x or bundle in x.parents or x in bundle.parents for x in mounts):
    raise SystemExit('STOP: bundle overlaps a protected/worker path')
env = {'PATH':'/usr/sbin:/sbin:/usr/bin:/bin','HOME':'/root','GIT_CONFIG_NOSYSTEM':'1','GIT_TERMINAL_PROMPT':'0'}
def git(*args):
    if args[0] == 'show':
        size = git('cat-file','-s',args[1]).strip()
        if not size.isascii() or not size.isdecimal(): raise SystemExit('STOP: merged blob size invalid')
        if int(size) > 65536: raise SystemExit('STOP: merged blob too large')
    result = subprocess.run(['git','--git-dir='+str(source),*args], capture_output=True,
                            check=True, timeout=15, env=env)
    if len(result.stdout) > 65536: raise SystemExit('STOP: merged blob too large')
    if args[0] == 'show' and len(result.stdout) != int(size):
        raise SystemExit('STOP: merged blob size changed')
    return result.stdout
if git('cat-file','-t',merge) != b'commit\n': raise SystemExit('STOP: merge absent')
index = json.loads(git('show',merge+':ops/bridge_one_shot/operator_artifacts.json'))
files = index['files']
if index['schema'] != 1 or len(files) != 11 or len(set(files)) != 11 or any(
        not x.startswith(('ops/bridge_one_shot/','ops/github_inbox/')) or
        pathlib.PurePosixPath(x).name != x.split('/')[-1] for x in files):
    raise SystemExit('STOP: unexpected merged artifact inventory')
blobs = {name: git('show',merge+':'+name) for name in files}
if len({pathlib.PurePosixPath(x).name for x in files}) != len(files):
    raise SystemExit('STOP: colliding helper basenames')
bundle.mkdir(mode=0o700)
checks = {}
worker_helpers = {'worker_probe.py', 'connect_proxy.py'}
for name, data in sorted(blobs.items()):
    path = bundle / pathlib.PurePosixPath(name).name
    mode = 0o444 if path.name in worker_helpers else 0o600
    fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd,'wb') as stream:
        stream.write(data); stream.flush(); os.fchmod(stream.fileno(), mode); os.fsync(stream.fileno())
    checks[name] = hashlib.sha256(data).hexdigest()
manifest = json.dumps({'schema':1,'merge':merge,'sha256':checks},sort_keys=True).encode()
path = bundle/'merged-byte-manifest.json'
fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW, 0o600)
with os.fdopen(fd,'wb') as stream:
    stream.write(manifest); stream.flush(); os.fsync(stream.fileno())
if {x.name for x in bundle.iterdir()} != {pathlib.PurePosixPath(x).name for x in files}|{path.name}:
    raise SystemExit('STOP: staged file set changed')
for name, digest in checks.items():
    if hashlib.sha256((bundle/pathlib.PurePosixPath(name).name).read_bytes()).hexdigest()!=digest:
        raise SystemExit('STOP: staged digest changed')
dirfd = os.open(bundle,os.O_DIRECTORY|os.O_RDONLY|os.O_NOFOLLOW)
try: os.fsync(dirfd)
finally: os.close(dirfd)
print('STAGED ONLY: exact merged bytes and manifest verified; procedure not run')
PY
```

Syntax-check each staged Python file with `python3 -I -B -m py_compile` **only in an operator-approved scratch/cache location** (or use `ast.parse` to avoid bytecode writes in the protected bundle), `bash -n` on `worker_firewall.sh`, and static `docker compose --env-file /dev/null ... config -q` with the private plan values. Recheck staged exact file set, mode, SHA and approved merge object after any move. This preparation did not run the block or inspect private host paths.

## Separate, future execution decision — **STOP pending manager/operator proof**

The following is not part of the staging block and is **not authorization to run it now**. If every NO-GO item is independently closed, a root operator may review a *single* invocation against one new attempt and private plan:

```sh
# FUTURE SEPARATELY AUTHORIZED ROOT INVOCATION ONLY; NOT RUN IN THIS PR.
python3 -I -B "$BUNDLE/operator_host.py" --execute --plan "$ROOT_ONLY_PLAN"
```

The root-only `bridge_readback.py` opens the journal through the host-private bind source but validates the recorded worktree against the container path `/state/queue/<queue-id>/bridge/worktrees/<run-id>`. It accepts GitHub ref objects with their normal URL metadata while checking exact ref/type/SHA. From the independently fetched, digest-pinned #43 issue body, it derives the approved UTF-8 Markdown bytes (including the final newline), requires exactly one added `docs/ONE_SHOT_REVIEW_NOTE.md` in the base-to-head compare, and fetches that file at the exact head to match size, content and Git blob identity. The signer permits only that fixed contents GET. A pending historical journal/receipt CI observation may advance; current CI is reported only from independent exact-head readback. These checks are repository-only until host proofs and a separate activation decision exist.

`operator_host.py --review` only prints a dormant status. The real entry first verifies private scope and public verifier against worker authorization, immutable merged blobs, clean runner pin, empty queue/inbox, image/network/firewall baselines and path separation. It fsyncs a fresh journal before proxy/network/firewall/container effects. It pauses at the exact worker ID for a finite **human device-login handoff** into the dedicated home (operator separately confirms `gh auth setup-git`); then its bundled `worker_probe.py` runs **inside that container** and returns only booleans for authenticated GitHub issue GETs and Git `ls-remote`. No preparation-shell credential is accepted as evidence. The root entry enrolls #41/#45 **disabled**, compares freshly captured cursors to its root-protected scope, enables only this one in-process inbox session (no timer), scans at most five bounded pages/issue for a fresh exact manager instruction, signs the canonical v1 payload once, stores POST intent before its one grant POST, and lets Inbox claim and dispatch **once**. A bounded empty feed creates no claim and may undergo exact-ID cleanup with a blocked/no-task report. The signed grant and any uncertain sign/POST/429/claim remain private durable reconciliation cases; no second signature, POST or dispatch. A granted claim receives a bounded dispatch budget. A Docker-client timeout or interrupt is **not** a child stop: the root entry checks the exact labeled worker ID, stops that container, and independently inspects its stopped state. If that observation fails it records runtime status as unknown, retains the claim intent and all private evidence, and never redispatches or claims cleanup. Signer HTTP pages, fences, signature subprocesses and grant/report POSTs receive the remaining monotonic deadline; an exhausted scan cannot borrow the cleanup reserve. The protected `bridge_readback.py` runs **only on root** from the hash-checked private bundle, never from the worker's mutable runner or worker stdout. It reads the worker journal as an untrusted claim and uses the separate root credential for fresh authenticated issue/comment, branch, draft, ancestry and exact-head CI GETs before reporting independently verified completion. The root readback credential must also resolve to the **same reviewed GitHub publisher identity** as the worker Bridge receipts (even though its token is separately stored and root-only); otherwise author verification fails closed. That actor relationship is a future host/credential proof, not inferred from a local CLI or a passing fixture. Pending CI is reported as pending, never success.

On a fully identified path, it disables the inbox without deleting cursor/state, stops/removes only the identified worker, rolls back the reviewed scoped firewall after exact status, stops/removes only the identified proxy and then removes only empty, labeled, exact-ID networks. It verifies original Docker resource baselines and disabled enrollment before publishing a bounded sanitized #41 report from the separate root route and refetching its exact comment ID/body. A partial startup, identity mismatch, missing baseline, unverified cleanup or lost report response is **NO-GO with retained evidence**, not a cleanup/success claim. Queue, journal, worktree, credential home, prior services/releases and historical runs are never deleted. Static/fake tests cannot establish actual host cleanup or manager-only App invocation.
