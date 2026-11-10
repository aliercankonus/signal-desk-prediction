# Corrected preflight for the unfinished authentication-only boundary

The first #70 operator entry returned unverified GitHub/provider checks and verified
exact cleanup with `AUTH_ERROR_CALLEDPROCESSERROR`. Its output did not identify the
failed child. Do not rerun it or delete its journal. The source flow does not reach
device login while GitHub verification is false; this does not prove model entitlement.

Manager reproduced a separate concrete blocker with real Git: normal clone plus
detached checkout preserves `branch.main.remote/merge`, and the frozen owner checker
rejects them. `worker_preflight_v3.py` accepts only complete origin/self-branch tracking
pairs with single exact values. Includes, credential/hook/filter/fsmonitor/SSH keys,
extra branch settings, duplicate/incomplete pairs and changed tracking values fail.
Actual UID/GID, canonical remote, clean pinned HEAD, private helper config, bounded
read-only Git calls and Git ownership safety checks remain unchanged. No safe.directory.

`authenticate_worker_clone_fix.py` is a distinct reviewed operator entry within the
existing user-approved, unfinished auth-only boundary. It does not resume/replay a
task or automatically invoke a host action. It requires the exact first root-private
receipt: GitHub/device false, cleanup true, no partial startup, no signing/enrollment/
timer/dispatch, known failure, and a final cleanup journal with no owned resources,
pending effect, report or unresolved state. Missing or different evidence stops.
Actual daemon/network/firewall preflight also runs again before any new effect.

The original journal, v2 bundle, private spec/scope/start/cursors, runner and all auth
files are preserved. A separate `auth-only-02` journal is exclusive and blocks another
invocation. It writes only the embedded reviewed public v3 preflight there, fsyncs it,
and mounts that file read-only at the existing worker preflight target. It never edits
the frozen v2 bundle or runner config. All other #70 confinement, readonly mounts,
device timeout, exact-ID cleanup and private receipt rules remain in force. Fixed
failure-stage/owner-code markers replace the previous opaque failure reporting;
raw stdout/stderr, accounts, URLs, credentials and tokens are never copied to receipts.

The existing explicit user approval covers only temporary scoped network/container/
firewall setup, worker authenticated read-only GitHub checks, and the still-unreached
single operator-approved device flow. Automation never executes host actions. Model
inference, real task dispatch, signing, enrollment, hourly timer and trading remain
unauthorized. App exclusivity and full image/host trust remain separate prerequisites;
passing this step is not autonomous-loop GO. #45 stays dormant; #44 is subsequent.

After exact-head CI/review/merge the manager supplies one filled pinned/hash-verified
operator entry. It requires the same live terminal/browser approval and preserves
private state on any STOP/timeout/interruption. No automatic retry, force removal,
prune or alternative attempt. Share only fixed final summary lines, never device codes.

## Immutable corrected operator entry

Only after review, exact-head CI and merge, under the existing explicit auth-only
approval. Do not use the old entry or delete its state. The manager supplies the
known existing private workspace; this block does not require a new spec or token.

```bash
python3 -I -B - "$EXISTING_PRIVATE_WORKSPACE" <<'PYCODE'
import hashlib, os, signal, sys, urllib.request
source = 'c04f5103011882cc0f0649fba7ae72e5fbbf022c'
digest = '45d00dfc94aabb4e175de2a72bd0389bfbdffaed66b57e86e9f6b633dfbf9d97'
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): raise RuntimeError('redirect refused')
def expired(*_): raise TimeoutError()
signal.signal(signal.SIGALRM, expired)
signal.alarm(20)
try:
    url = 'https://raw.githubusercontent.com/aliercankonus/signal-desk-prediction/'+source+'/ops/bridge_one_shot/authenticate_worker_clone_fix.py'
    with urllib.request.build_opener(NoRedirect).open(url, timeout=15) as response:
        data = response.read(65537)
    if len(data)>65536 or hashlib.sha256(data).hexdigest()!=digest:
        raise RuntimeError('digest mismatch')
except Exception:
    print('STOP: CORRECTED_AUTH_SOURCE_UNVERIFIED; preserve state; no retry')
    raise SystemExit(1)
finally:
    signal.alarm(0)
namespace = {'__name__':'reviewed_clone_correction'}
exec(compile(data, '<reviewed-clone-correction>', 'exec'), namespace)
sys.argv = ['auth-only', '--workspace', sys.argv[1], '--authenticate']
try:
    tty = os.open('/dev/tty', os.O_RDWR)
    os.dup2(tty, 0)
    sys.stdin = os.fdopen(os.dup(tty), 'r', buffering=1)
    os.close(tty)
except OSError:
    print('STOP: LIVE_OPERATOR_TTY_REQUIRED; no runtime started')
    raise SystemExit(1)
raise SystemExit(namespace['main']())
PYCODE
```
