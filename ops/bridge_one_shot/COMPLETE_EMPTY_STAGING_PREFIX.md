# Complete only the observed empty pre-runtime staging prefix

Operator metadata after #62/#63 shows the original root-private spec/bootstrap
and eight initial directories with expected owners, but no claim state, policy,
plan or staging receipt. Metadata does not prove directory emptiness. V2 uses
mkdir without parents=True and never prepares the fixed claim parent before
creating the preceding directories; a missing parent can leave exactly this
prefix. The original syscall exception was not captured. Do not assert that
parent absence was directly observed, or call the old effectful entry again.

This separately reviewed operator entry is restricted to the exact
`issue41-cold-20261110-01` inert prefix and original frozen spec/cursors. Default
is read-only preview. Explicit `--complete` requires all eight directories to
exist, be real directories with exact UID/GID/0700 and contain zero entries. It
checks the original root-0600 spec and frozen v2 bootstrap digest, protected cold
receipts and public verifier. Private key/token inputs are metadata-only; their
contents are never opened, copied or installed. All source/runner/adapter/mount,
image-names and static Compose gates remain in the staging engine.

Any nonempty/symlink/wrong-owner directory, existing queue/claim/output/handoff,
changed original spec/source, prior completion intent or receipt stops before
completion. The entry never adopts or repairs an old worktree, blocked task,
queue, credential or claim. Historical runs and the original runner remain intact.

V3 preflights the fixed claim parent's trusted root ancestry before writes.
After all admission checks it exclusively writes/fsyncs one root-private
completion intent. Only if missing, it creates that one fixed parent at 0700;
existing trusted root-owned parents are left as-is, never chmodded/chowned.
It retains the exact empty prefix directories and completes the remaining fresh
inert staging, including the fixed claim directory. The runner remains root-owned
through root Git operations and transfers only after final HEAD/cleanliness
checks. All publication remains exclusive; no reset, deletion or overwrite.
The original spec, original start/cursors and v2 bootstrap file stay unchanged.
The final receipt separately identifies the preserved source and v3 completion
engine. This is not permission to rewrite an authority window or reuse a claim.

Expected: PREFIX_COMPLETION STAGED_NO_ACTIVATION; ORIGINAL_SPEC_BOOTSTRAP
PRESERVED; WORKER_CREDENTIALS NOT_INSTALLED; PROVIDER_AUTH NOT_STARTED; overall
NO-GO. No signer/grant, provider login/request, worker/container/network/service,
persistent scheduler or real dispatch is activated. Installed watcher, actual
worker authentication, manager/App exclusivity and first loop remain UNPROVEN.

## One reviewed operator block

Manager supplies the immutable commit/SHA256 and known private workspace in this
complete block. Public source dependencies have individual pinned SHA256 gates;
no mutable-branch or arbitrary URL code is accepted. The loader does not write
its downloaded source. Ali does not reconstruct JSON, locate paths or relay work.

```bash
env -i PATH=/usr/bin:/bin HOME=/root LC_ALL=C \
  SD_PREFIX_COMMIT='MANAGER_REVIEWED_COMMIT' \
  SD_PREFIX_SHA256='MANAGER_REVIEWED_SHA256' \
  SD_PREFIX_WORKSPACE='MANAGER_SUPPLIED_PRIVATE_WORKSPACE' \
  /usr/bin/python3 -I -B - <<'PY'
import hashlib, os, re, signal, sys, urllib.request
commit, digest = os.environ['SD_PREFIX_COMMIT'], os.environ['SD_PREFIX_SHA256']
if os.geteuid() != 0 or not re.fullmatch('[0-9a-f]{40}',commit) or not re.fullmatch('[0-9a-f]{64}',digest):
    raise SystemExit('STOP: INVALID_PREFIX_PIN')
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): raise ValueError('redirect')
def timeout(*args): raise TimeoutError()
previous=signal.signal(signal.SIGALRM,timeout)
signal.alarm(20)
try:
    url=('https://raw.githubusercontent.com/aliercankonus/signal-desk-prediction/'+
         commit+'/ops/bridge_one_shot/complete_empty_staging_prefix.py')
    with urllib.request.build_opener(NoRedirect).open(url,timeout=15) as response:
        source=response.read(32769)
    if len(source)>32768 or hashlib.sha256(source).hexdigest()!=digest: raise ValueError('digest')
except Exception:
    raise SystemExit('STOP: PUBLIC_PREFIX_SOURCE; completion not called')
finally:
    signal.alarm(0)
    signal.signal(signal.SIGALRM,previous)
sys.argv=['reviewed-prefix','--workspace',os.environ['SD_PREFIX_WORKSPACE'],
          '--source-commit',commit,'--complete']
exec(compile(source,'<reviewed-prefix>','exec'),{'__name__':'__main__'})
PY
```

On any new STOP, timeout or interruption, preserve everything and do not invoke
completion again. There is no automatic retry, cleanup or alternate attempt.
New error lines contain only a fixed reason, exception category and reviewed
public-code function/line; no exception text, private values or file paths.
Return only those fixed status/error lines. #44 single-container reproducibility
and separately secured persistent backup/restore remain subsequent acceptance.
