# Dedicated Git helper and versioned runtime preparation

The #68 operator receipt passed worker identity, actual owner Git HEAD/cleanliness,
Git, Hermes presence, interpreter/pytest versions, and exact probe cleanup. The
image lacks `gh`. That old probe result remains BLOCKED under its original contract;
do not rerun its intent, remove a gate without a replacement, or claim authentication.

The frozen Bridge uses `git credential fill` plus bounded Python REST, not `gh`.
V2 adds a dedicated Git helper and retains the pinned runner. No host package or
new agent framework is needed. The helper serves HTTPS `github.com` only, limits
explicit Git paths to this exact repository (optional `.git`), rejects unexpected
fields and usernames, and never persists `store`/`erase`. Host-only GET is deliberately
supported for frozen Bridge REST; this cannot itself enforce a REST repository path.
Separately verified repository-specific server grants, the unchanged REST allowlist,
authenticated worker GETs and independent root readback remain required. The helper
never prints errors containing request/credential values. Its credential-protocol
stdout is consumed privately by Git; do not run `git credential fill` interactively.

`operator_host_v2.py` / `operator_artifacts_v2.json` / `compose.operator.v2.yml`
are separately versioned files. The original adapter, bootstrap/spec, runner,
home/auth state and completed probe are preserved. Historical runner
`00acd27132b68264ee2ab1692d3024f09c640c6d` remains untouched; reviewed candidate
`e84021a786004456a12de9e25eae50d191da6cf1` is retained. No `safe.directory` bypass.
V2 removes root Git access to the worker-owned runner. A read-only owner/config
gate executes inside the recorded worker before the provider handoff or GitHub
credential use. This gate never retrieves a credential. Root file containment checks
use actual protected objects against exact worker mount sources, rather than wrongly
treating their common root-private workspace as a credential mount. Ownership and
ancestor protections remain intact. Two new helpers are root-owned read-only mounts.

## Explicit operator preparation boundary

The manager automation must never run `prepare_worker_runtime_v2.py` on the VPS.
Review mode validates existing protected setup/spec/staging/probe records and inert
queue/journal state without reading a credential or changing files. It retrieves
bounded hash-verified public helper/release metadata. `--prepare` additionally:

1. Writes an exclusive durable root-only intent; any existing v2 path stops.
2. Retrieves hash-verified public v2 artifacts and fetches only the exact reviewed
   public commit into the protected bare source. Git uses no ambient credential,
   hooks, redirects, lazy fetch or submodules; refs, HEAD and FETCH_HEAD must match.
3. Creates new root-private v2 bundle/plan plus dedicated UID:GID 10000:10000 auth/home
   directories. Uses the original unchanged policy and device-only provider config.
4. Copies the operator-supplied dedicated worker credential from its root-private
   input into only the new auth directory as mode 0400, UID:GID 10000:10000. This is a
   credential filesystem operation and requires the operator's explicit decision to
   run `--prepare`. No token is printed, passed as an argument or written to Git config.
5. Records a private sanitized receipt. Does not invoke Docker, provider/Hermes,
   authenticated GitHub checks, signing, enrollment, scheduler, service or task dispatch.

The root/public source and bundle are not worker mounts. No root key or readback
credential is copied to worker auth. Do not construct another spec, obtain another
token, change the runner, adopt existing Hermes profiles, or refresh task windows or
cursors. Original cold/input/staging files remain unchanged. V2 plan changes only
bundle/auth/home paths and the separately reviewed artifact commit. No main/service
deployment is triggered by merging these preparation sources.

The manager supplies one filled immutable loader privately. The canonical source
and digest are embedded in that loader after review. The workspace is an existing
private input, never a repository value. Preparation is explicitly separate from
running `operator_host_v2.py --execute`: that execution is **not authorized** by this
procedure. Missing isolation/manager-exclusive invocation proof, provider device
authentication, actual worker authenticated reads and the first approved #43 roundtrip
remain separate. #45 scheduler remains dormant; #44 portability/restore follows.

Expected `RUNTIME_V2: PREPARED_NO_ACTIVATION`, original staging/source refs preserved,
dedicated read-only worker credential installed, and no provider/services/tasks
started; overall NO-GO. STOP, partial output, timeout or interruption: preserve all
files/intents/source objects; no automatic retry, deletion, reset or substitute attempt.
Preparation CI proves only source behavior; it is not VPS acceptance or token scope.

## Canonical hash-verified operator entry

Run only after substantive manager review/merge and exact-head CI. This explicit
`--prepare` entry performs the filesystem credential operation described above;
it does not start authentication, isolation services or real work. The manager
substitutes the known private workspace; no path search or file editing is needed.

```bash
python3 -I -B - "$EXISTING_PRIVATE_WORKSPACE" <<'PYCODE'
import hashlib, signal, sys, urllib.request
source = '42db985bba2f0a64ce8d848e39a11c2a18c689f3'
digest = 'dd23fab9ac0f1c39ae7d8e158781fa6f0cca6c6d5b1b98da3aba5c851aefa245'
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): raise RuntimeError('redirect refused')
def expired(*_): raise TimeoutError()
signal.signal(signal.SIGALRM, expired)
signal.alarm(20)
try:
    url = 'https://raw.githubusercontent.com/aliercankonus/signal-desk-prediction/'+source+'/ops/bridge_one_shot/prepare_worker_runtime_v2.py'
    with urllib.request.build_opener(NoRedirect).open(url, timeout=15) as response:
        data = response.read(65537)
    if len(data)>65536 or hashlib.sha256(data).hexdigest()!=digest:
        raise RuntimeError('digest mismatch')
except Exception:
    print('STOP: REVIEWED_V2_SOURCE_UNVERIFIED; preserve state; no retry')
    raise SystemExit(1)
finally:
    signal.alarm(0)
namespace = {'__name__':'reviewed_runtime_v2_preparation'}
exec(compile(data, '<reviewed-v2-preparation>', 'exec'), namespace)
sys.argv = ['prepare', '--workspace', sys.argv[1], '--source-commit', source, '--prepare']
raise SystemExit(namespace['main']())
PYCODE
```
