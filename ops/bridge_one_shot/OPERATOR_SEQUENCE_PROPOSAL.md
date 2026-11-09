# #41 operator installation proposal — reviewed source, NOT a host run

This is a **proposal only** against the reviewed `main` merge `0fbf46053a74bad4a35ecb3d324b6decab530b83` (PR #53). Nothing below has been executed on the VPS. The old adapter is `eac843de7967d48cce56ee9a198750e98754a2de`, the *independent* frozen #43 task runner is `e84021a786004456a12de9e25eae50d191da6cf1`, and the existing bootstrap source is from `665698113fcd7d8f7d10a75ee42f67d8a2131166`. Do not substitute this proposal's future draft head/merge for any of those runtime pins. No old attempt, claim, credential, service or release is reset. The already accepted offline/CI tests are not repeated here.

## Evidence and hard gates

| Status | Observation / requirement |
| --- | --- |
| VERIFIED (repository/GitHub only) | `0fbf460…` is the PR #53 merge on `origin/main`; the dormant scheduler, guided spec helper, bootstrap, root installer, one-shot operator entry and inbox controls are present in its Git tree. PR #53's exact-head CI was successful; this is not a VPS receipt. #43 is open with its frozen English Markdown-only body. |
| REPORTED, not independently measured here | Earlier operator notes describe route-enforced off-link denial and a credential-free fixture. They do not establish the actual future worker's image-internal credential isolation, manager-only App invocation, current host inventory, installed source or readiness. |
| MISSING / STOP | A host-verified root-private bare Git object store with all pinned objects, trusted fresh/private parents and protected/excluded mount roots; inspected image ID, worker UID:GID, worker-owned venv and exact compatible test interpreter/requirements/versions; approved Git author identity and fresh exact #41/#45 cursors. The guide has a **fixed** test interpreter path; if it is absent inside the worker, stop—do not fabricate a host path or weaken the consumer. |
| MISSING / STOP | Distinct, separately provisioned root-owned 0600 signing key, matching public verifier and root GitHub readback credential; dedicated worker GitHub and provider identities with refreshable home. Credential scopes/GETs from the actual worker, root post-cleanup reporting, broad-credential inaccessibility, host mounts/routes and **manager-exclusive App invocation** must be proved independently. Neither a filename nor App metadata is proof. |
| MISSING / STOP | A dedicated persistent isolated worker, approved process supervisor and immutable runner/enrollment for a **new separately authorized task**. The existing Compose worker is a finite one-shot worker stopped/removed by the one-shot entry; it is not an hourly process. #43's completed/uncertain claim must never be recycled. |

Only the root operator can supply or validate these private facts; no JSON editing or guessed paths are required of Ali. No code here provisions keys/tokens, performs device login or tests actual host isolation. If a prerequisite cannot be established, STOP **before** the corresponding stage, and report the one missing input privately. No placeholder file or broad preparation credential is an acceptable substitute. The operator must independently approve each effectful phase; this document itself grants none.

## Future root terminal: immutable helper installation (private preparation phase)

**Not authorized by this proposal.** Only after independent host inventory and a protected bare store exist, the root operator supplies the *existing* store and an *existing, root-only private* destination parent **outside every agent bind, worker mount, application/data/release root and old attempt**. This block installs only the already reviewed guide and installer source bytes from the pinned merge; it does not stage the bootstrap or create a spec. A path failure or partial copy is STOP, not retry. The two SHA-256 values are of the exact Git blobs (no newline normalization).

```bash
# FUTURE PRIVATE ROOT TERMINAL ONLY — do not run from an agent shell.
set -Eeuo pipefail
set +x
umask 077
export PATH=/usr/sbin:/sbin:/usr/bin:/bin HOME=/nonexistent LC_ALL=C
[ "$(id -u)" -eq 0 ] || { printf 'STOP: root required\n' >&2; exit 1; }
read -r -s -t 120 -p 'Existing root-private bare Git store (absolute path): ' STORE </dev/tty; printf '\n'
read -r -s -t 120 -p 'Existing root-private destination parent (absolute path): ' PRIVATE_PARENT </dev/tty; printf '\n'
# Root must FIRST compare these paths against the actual protected roots and mounts.
# This check is not a substitute for host inventory or manager/credential isolation proof.
timeout -k 2s 60s python3 -I -B - "$STORE" "$PRIVATE_PARENT" <<'PY'
import hashlib, os, pathlib, stat, subprocess, sys
store, parent = map(pathlib.Path, sys.argv[1:])
merge = '0fbf46053a74bad4a35ecb3d324b6decab530b83'
items = {
    'prepare_operator_spec.py': 'c1bc75f44a195ac2d34ac8000a983a9bbb6ab74369c212c96d5504f544697f8a',
    'install_operator_bootstrap.sh': 'ee29f7b42e36b79ca46e8516e0fa3b0a321b481b2c244edf4970f81564da638d',
}
for p in (store, parent):
    if (not p.is_absolute() or str(p) == '/' or '..' in p.parts or
            str(pathlib.Path(str(p))) != str(p)):
        raise SystemExit('STOP: noncanonical private path')
    for part in (p, *p.parents):
        i = part.lstat()
        if not stat.S_ISDIR(i.st_mode) or i.st_uid != 0 or i.st_mode & 0o022:
            raise SystemExit('STOP: untrusted root ancestry')
    if p.stat().st_mode & 0o077:
        raise SystemExit('STOP: private directory not private')
if store == parent or store in parent.parents or parent in store.parents:
    raise SystemExit('STOP: source and destination overlap')
base = ['git', '--git-dir=' + str(store)]
env = dict(PATH='/usr/sbin:/sbin:/usr/bin:/bin', HOME='/nonexistent', LC_ALL='C',
           GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null',
           GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never')
def git(*args):
    result = subprocess.run([*base, *args], stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            timeout=15, env=env, check=True)
    if len(result.stdout) > 65536:
        raise SystemExit('STOP: Git output bound')
    return result.stdout
if git('rev-parse', '--is-bare-repository') != b'true\n' or git('cat-file','-t',merge) != b'commit\n':
    raise SystemExit('STOP: protected merge absent')
for name, expected in items.items():
    target = parent / ('issue41-' + merge + '-' + name)
    if target.exists() or target.is_symlink():
        raise SystemExit('STOP: immutable helper exists; preserve it')
    ref = merge + ':ops/bridge_one_shot/' + name
    blob = git('show', ref)
    if not blob or hashlib.sha256(blob).hexdigest() != expected or int(git('cat-file','-s',ref)) != len(blob):
        raise SystemExit('STOP: immutable helper digest/size mismatch')
    # Exclusive publication only after both helpers have passed provenance checks.
    items[name] = (target, blob, expected)
for name, (target, blob, expected) in items.items():
    root = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(target.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=root)
        with os.fdopen(fd, 'wb') as out:
            out.write(blob); out.flush(); os.fchown(out.fileno(), 0, 0); os.fsync(out.fileno())
        os.fsync(root)
    finally:
        os.close(root)
    if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
        raise SystemExit('STOP: installed helper digest mismatch; preserve partial state')
print('GUIDE AND INSTALLER SOURCE STAGED ONLY; no spec/bootstrap/runtime action')
PY
GUIDE="$PRIVATE_PARENT/issue41-0fbf46053a74bad4a35ecb3d324b6decab530b83-prepare_operator_spec.py"
INSTALLER="$PRIVATE_PARENT/issue41-0fbf46053a74bad4a35ecb3d324b6decab530b83-install_operator_bootstrap.sh"
# STOP for private review. Do not proceed on any failure or uncertain partial copy.
```

The root operator must additionally confirm the store contains bootstrap `665698113…`, adapter `eac843de…`, runner `e84021a…`, and that the fixed venv path and image actually match the intended isolated worker. This is a **separate** host inventory and private provisioning decision; the block above does not create any such inputs. Do not copy a signing key or credential from a shared Hermes profile.

## Future root terminal: guided spec and bootstrap staging (separate decisions)

After those missing prerequisites are independently supplied and the helper installation has been read back, the **existing** guide prompts for 19 operator-observed fields, including existing private file paths; it derives all fixed pins, fresh paths and policy values and validates the *existing* bootstrap consumer from the protected store. `PREVIEW READY` is a no-write result. `--write` repeats the prompts and exclusively writes a new 0600 spec; the operator must supply the same fresh attempt and verified inputs. No one edits JSON. Ali must not guess the spec path: it is precisely `<private_parent>/<attempt>-bootstrap-spec.json`, derived from the two values the operator entered into the guide, and must be confirmed privately before continuing. The guide does not print private paths.

```bash
# FUTURE PREVIEW ONLY, after the preceding STOP and separate operator approval.
timeout -k 2s 2400s python3 -I -B "$GUIDE"
# Expected PREVIEW READY; STOP. No spec and no bootstrap has been installed.
```

```bash
# FUTURE EXPLICIT PRIVATE SPEC-WRITE DECISION, not implied by preview.
timeout -k 2s 2400s python3 -I -B "$GUIDE" --write
# Expected SPEC WRITTEN ONLY; STOP. Derive/verify the private spec path below.
read -r -s -t 120 -p 'Same attempt ID entered in the guide: ' ATTEMPT </dev/tty; printf '\n'
read -r -s -t 120 -p 'Same existing private_parent entered in the guide: ' SPEC_PARENT </dev/tty; printf '\n'
SPEC="${SPEC_PARENT%/}/$ATTEMPT-bootstrap-spec.json"
timeout -k 2s 15s python3 -I -B - "$SPEC" "$ATTEMPT" <<'PY'
import json, os, pathlib, re, stat, sys
p, attempt = pathlib.Path(sys.argv[1]), sys.argv[2]
if not re.fullmatch('[a-z][a-z0-9-]{5,63}', attempt) or not p.is_absolute() or '..' in p.parts or str(p) != sys.argv[1]:
    raise SystemExit('STOP: invalid derived spec path')
for part in (p.parent, *p.parent.parents):
    i = part.lstat()
    if not stat.S_ISDIR(i.st_mode) or i.st_uid != 0 or i.st_mode & 0o022:
        raise SystemExit('STOP: untrusted spec ancestor')
i = p.lstat()
if not stat.S_ISREG(i.st_mode) or i.st_uid != 0 or i.st_mode & 0o077 or not 0 < i.st_size <= 16384:
    raise SystemExit('STOP: spec metadata mismatch')
with p.open('rb') as f: data = f.read(16385)
if len(data) != i.st_size or json.loads(data)['attempt'] != attempt:
    raise SystemExit('STOP: spec attempt mismatch')
print('PRIVATE SPEC VERIFIED; no source installation or staging')
PY
# STOP: an existing, reviewed spec is now available; keep its path private.
```

Use the **already reviewed** `ROOT_OPERATOR_ENTRY.md` preparation block verbatim, not a reconstructed/bootstrap shortcut: the installed `$INSTALLER` prompts for the now-existing `$SPEC`, verifies the older bootstrap blob SHA-256 `e79f337fcbefc4f21f4d6d4abd2e30078227cb0913f242b552630fd110c1dd0d`, and exclusively installs it at a spec-derived root-only path. Because that script uses `return` at top level for failure handling, **source** it in the same trusted interactive Bash shell (do not execute it as `bash file`), after checking its installed digest. Its success marker is `IMMUTABLE ENTRY STAGED ONLY; bootstrap procedure NOT RUN`. Then STOP for a distinct staging authorization:

```bash
# FUTURE SOURCE INSTALLATION ONLY; no --stage and no --execute.
[ "$(sha256sum "$INSTALLER" | cut -d' ' -f1)" = ee29f7b42e36b79ca46e8516e0fa3b0a321b481b2c244edf4970f81564da638d ]
# It privately asks for the already verified SPEC; paste that exact path, not JSON.
source "$INSTALLER"
# Expected IMMUTABLE ENTRY STAGED ONLY; STOP for review.
```

```bash
# FUTURE ONE-TIME STAGING ONLY, requiring another operator approval in SAME root shell.
# ENTRY, SPEC and BLOB_SHA must be inherited from the successful installer source.
[ -n "${ENTRY:-}" ] && [ -n "${SPEC:-}" ] && [ "${BLOB_SHA:-}" = e79f337fcbefc4f21f4d6d4abd2e30078227cb0913f242b552630fd110c1dd0d ]
[ "$(sha256sum "$ENTRY" | cut -d' ' -f1)" = "$BLOB_SHA" ]
timeout -k 2s 620s python3 -I -B "$ENTRY" --stage --spec "$SPEC"
# Expected STAGED ONLY — activation NO-GO; manager-exclusive invocation UNPROVEN.
```

The guide and bootstrap refuse absent/private-path and existing-destination mismatches; preserve partial names if interrupted, never rerun on an ambiguous stage. The bootstrap creates only fresh bundle/runner/state/auth/context/home/inbox/plan and **disabled** enrollment input; it neither logs in nor starts a worker. The fixed #43 runner/task branch remains `e84021a…` / `issue43-one-shot-review-note`. Confirm that branch and matching PR are absent, exact #43 body digest matches `c9e4e393ccc506954f0a18e6eaeea7c82ff598b0b41eac642d7f88da1fca73c6`, and freshly captured #41/#45 cursors agree before the later runtime; otherwise STOP and seek a new reviewed attempt, not a reset.

## Future first frozen #43 roundtrip — NOT AUTHORIZED HERE

STOP until an independent operator/manager decision establishes actual worker mount/credential isolation, manager-exclusive App invocation, route/firewall acceptance, supported dedicated GitHub/Checks/Actions permissions, provider/device flow and root readback identity. Record a fresh attempt approval bound to the exact private plan; never infer approval from the existence of a staged spec. The existing `operator_host.py` owns the finite attempt, disabled enrollment, root-side signer, one inbox claim, Bridge draft PR publication, read-only artifact/head/CI verification, exact-ID cleanup and post-cleanup #41 report. Its transient worker is **removed** after the attempt. A quiet feed is a bounded no-task result, not permission to sign again or replay. It may pause for private human GitHub/provider device login in the exact identified worker ID; use the *separate* bounded device-login block from `BOOTSTRAP_HANDOFF.md` only after the operator checks the image's CLI/config and remaining overall deadline. Do not put codes/tokens in shell history, issue comments or this proposal. Before the **one** separately authorized invocation, derive `BUNDLE` and `PLAN` from the root-owned spec under the same trusted private parent, not manual JSON edits; the operator can privately inspect the existing spec and run the following **read-only** derivation in the root shell:

```bash
META="$(timeout -k 2s 15s python3 -I -B - "$SPEC" <<'PY'
import json, os, pathlib, stat, sys
p = pathlib.Path(sys.argv[1])
if not p.is_absolute() or '..' in p.parts or str(p) != sys.argv[1]: raise SystemExit('STOP: spec path')
for q in (p.parent, *p.parent.parents):
    i=q.lstat()
    if not stat.S_ISDIR(i.st_mode) or i.st_uid != 0 or i.st_mode & 0o022: raise SystemExit('STOP: ancestry')
i=p.lstat()
if not stat.S_ISREG(i.st_mode) or i.st_uid != 0 or i.st_mode & 0o077 or not 0 < i.st_size <= 16384: raise SystemExit('STOP: spec')
c=json.loads(p.read_bytes())
for k in ('bundle','plan'):
    v=c[k]
    if not isinstance(v,str) or not v.startswith('/') or '..' in pathlib.Path(v).parts or str(pathlib.Path(v)) != v or '\n' in v:
        raise SystemExit('STOP: derived path')
    print(v)
PY
)"
BUNDLE=${META%%$'\n'*}; PLAN=${META#*$'\n'}
[ -n "$BUNDLE" ] && [ -n "$PLAN" ] && [[ "$PLAN" != *$'\n'* ]]
# STOP and review the private plan, source hashes, exact worker baseline/credentials and approval.
```

The root entry is **one** separately authorized invocation:

```bash
# FUTURE SINGLE ATTEMPT ONLY. Requires separately approved plan and all GO proofs.
[ -n "${BUNDLE:-}" ] && [ -n "${PLAN:-}" ]
timeout -k 2s 7500s python3 -I -B "$BUNDLE/operator_host.py" --execute --plan "$PLAN"
# Never repeat after timeout, missing receipt, blocked claim or uncertain cleanup.
```

A timeout of the outer client is not evidence the Docker child stopped. Reconcile the exact preserved journal, inbox claim, queue/worktree, remote branch/draft/head and exact-head checks **read-only**; no retry, duplicate POST or manual PR creation. `review-ready` must include verified cleanup and post-cleanup report readback; pending CI remains pending. A completed #43 claim is exhausted, not reusable for later tasks.

## Future dedicated worker and hourly :30 scheduler — additional installation decision

**NOT GO from the one-shot package.** Its Compose worker/proxy use `restart: no` and the root operator tears them down. The reviewed `compose.inbox.candidate.yml` is also one-shot, not an installed persistent supervisor. First approve a separate dedicated, refreshable, isolated worker and process supervisor using the same reviewed image/runner provenance and existing `Inbox.tick → BridgeQueue → Bridge.once` code; verify actual mounts and routes, no shared Hermes home/credential, correct non-root UID, immutable runner, worker credential and resource/stop/restart policy. A new task needs a new reviewed signed authority, private authorization/context and fresh **disabled** enrollment with #41/#45 cursors captured after the #43 result. Never point the scheduler at #43's completed/uncertain claim. The manager-only root signer must be separately protected and enabled under its own approval; a GitHub comment alone cannot create authority.

Within that **already installed** worker namespace, the only runner controls are the existing commands below. `/workspace/runner`, `/private/inbox/enrollment.json`, `/state/github-inbox` and `/opt/hermes/.venv/bin/python` are the reviewed *container paths*, not assertions about host paths. The operator must independently verify those mounts, runner pin, worker/container ID and fresh authorization before any enrollment. `--start` is the actual fresh UTC enrollment instant; old comments are inert. The first block creates **disabled** state and stops; do not use a second direct one-shot caller.

```bash
# FUTURE COMMANDS INSIDE THE APPROVED DEDICATED WORKER ONLY; separate authorization.
/opt/hermes/.venv/bin/python -I -B /workspace/runner/ops/github_inbox/inboxctl.py \
  enroll --enrollment /private/inbox/enrollment.json --state /state/github-inbox \
  --start "$FRESH_REVIEWED_UTC_ENROLLMENT_INSTANT"
/opt/hermes/.venv/bin/python -I -B /workspace/runner/ops/github_inbox/inboxctl.py \
  doctor --enrollment /private/inbox/enrollment.json --state /state/github-inbox
# Verify disabled, no claim and frozen cursor; STOP for separate enable/scheduler approval.
```

```bash
# FUTURE DISTINCT ENABLE/SUPERVISOR AUTHORIZATION INSIDE THAT SAME WORKER.
/opt/hermes/.venv/bin/python -I -B /workspace/runner/ops/github_inbox/inboxctl.py \
  enable --enrollment /private/inbox/enrollment.json --state /state/github-inbox
# One approved supervisor (not cron plus another watcher) executes precisely:
exec /opt/hermes/.venv/bin/python -I -B /workspace/runner/ops/github_inbox/hourly_scheduler.py \
  --enrollment /private/inbox/enrollment.json --state /state/github-inbox
```

The supervisor must supply the existing dedicated home/proxy environment and finite restart policy, never relaunch a claimed task to satisfy the clock. Its single process holds `scheduler.lock`; each tick is bounded to 3300 seconds. It targets real `:30 Europe/Amsterdam` slots, skips nonexistent/missed slots, distinguishes both autumn 02:30 instants, and spends no model call on an empty poll. A crash/429/blocked or uncertain claim requires read-only reconciliation, not automatic task redispatch. For rollback, stop **the exact identified supervisor process first**, verify it stopped, then use `inboxctl.py disable` and `doctor`; preserve the queue, claim, journals, credentials and remote receipts. A persistent deployment/service definition, its host path/ID and a verified first roundtrip **do not yet exist**; these command blocks cannot be used as a claim of installed scheduling. #44 clean-host restore remains separate.
