# Read-only Git probe after the #64 command failure

The operator reported RuntimeError at _bounded_run:117, meaning a bounded Git or
Docker subprocess returned nonzero. Its command/output was withheld. This is not
proof that another stage completed; do not rerun or clean any existing state.

A real offline Git regression identifies a concrete source-transfer defect:
when a protected bare store contains a pinned commit but no refs, clone with
--no-local --no-checkout succeeds but does not transfer that unreachable commit.
The existing fixture had refs, so it missed this condition. A bounded local-only
exact-SHA fetch transfers it without refs or FETCH_HEAD writes in the offline
experiment; that is candidate correction evidence only, never executed by this
probe and not VPS recovery authorization.

The root-only probe reads the protected nonsecret setup manifest, validates
root-owned source/runner metadata and reads only Git object/ref/HEAD metadata.
It never reads token/key/auth contents, file bodies from the worktree or stderr.
It outputs fixed labels, never private paths, Git refs or arbitrary command output.
Commands are fixed cat-file -t, rev-parse --verify HEAD and for-each-ref --count=1,
with global/system Git config and ambient credentials disabled. No status or
fsmonitor, fetch, checkout, reset, clone, hooks, Docker, staging or writes occur.
Missing runner .git never causes traversal into a parent repository. Presence of
an unexpected commit/ref/tree entry is preserved, not accepted as an empty clone.

## Operator entry

Manager fills this one immutable block with the known private workspace. Public
source is hash-checked before execution, with no redirects, a size cap and finite
timeouts. Return fixed SOURCE/RUNNER/PREFIX_INTENT/STAGING_RECEIPT lines plus
READ_ONLY_COMPLETE, or STOP; never return private configs or raw Git errors.

```bash
env -i PATH=/usr/bin:/bin HOME=/root LC_ALL=C \
  SD_PROBE_COMMIT='MANAGER_REVIEWED_COMMIT' \
  SD_PROBE_SHA256='MANAGER_REVIEWED_SHA256' \
  SD_PROBE_WORKSPACE='MANAGER_SUPPLIED_PRIVATE_WORKSPACE' \
  /usr/bin/python3 -I -B - <<'PY'
import hashlib, os, re, signal, sys, urllib.request
commit,digest=os.environ['SD_PROBE_COMMIT'],os.environ['SD_PROBE_SHA256']
if os.geteuid()!=0 or not re.fullmatch('[0-9a-f]{40}',commit) or not re.fullmatch('[0-9a-f]{64}',digest):
    raise SystemExit('STOP: INVALID_GIT_PROBE_PIN')
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('redirect')
def timeout(*args):raise TimeoutError()
previous=signal.signal(signal.SIGALRM,timeout);signal.alarm(20)
try:
    url=('https://raw.githubusercontent.com/aliercankonus/signal-desk-prediction/'+
         commit+'/ops/bridge_one_shot/probe_staging_git.py')
    with urllib.request.build_opener(NoRedirect).open(url,timeout=15) as response:
        source=response.read(16385)
    if len(source)>16384 or hashlib.sha256(source).hexdigest()!=digest:raise ValueError('digest')
except Exception:
    raise SystemExit('STOP: PUBLIC_GIT_PROBE_SOURCE; no probe called')
finally:
    signal.alarm(0);signal.signal(signal.SIGALRM,previous)
sys.argv=['reviewed-git-probe','--workspace',os.environ['SD_PROBE_WORKSPACE']]
exec(compile(source,'<reviewed-git-probe>','exec'),{'__name__':'__main__'})
PY
```

The automation never runs this on the VPS. A missing runner object alone does
not authorize fetching or checkout. Manager must reconcile actual intent,
empty-worktree/refs/HEAD evidence and exact pinned source before any separately
reviewed operator correction. Preserve original spec/cursors/authority windows,
all partial state, keys/tokens and historical runs. No real task, service,
scheduler, provider/model request or signer/grant is authorized.
