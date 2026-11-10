# Worker capability boundary after successful inert staging

This is a new, explicit **operator-only runtime probe**, not another staging attempt.
The manager automation must never invoke it on the host. Its default mode validates
existing protected preparation records without invoking Docker. `--probe` creates,
starts, and removes exactly one new temporary container. It does not enroll a worker,
install a watcher, start a project service, provision credentials, authenticate a
provider, sign a task, contact GitHub, or dispatch/retry any task.

The operator uses the existing private workspace. Do not publish its paths, image
metadata, tokens, raw logs or private records. The manager supplies the known path
privately; no manual JSON/spec or token re-creation is required.

The helper requires the successful #67 staging receipt, unchanged original spec and
matching root-owned plan/setup/cold metadata. It never opens root/worker tokens,
private keys or auth stores. It preserves every original staging file, scope window,
cursor, credential and historical run. It mounts only the worker-owned runner and
venv, both read-only, in a nonroot UID:GID 10000:10000 container using the existing
immutable image without pulling. Networking is `none`; root filesystem read-only;
capabilities dropped; privilege escalation disabled; memory, CPU, PID, command time
and output bounded. Fresh tmpfs masks the old `/opt/data` tree except the specific
read-only venv, and provides a fresh home. No existing container is executed or changed.

The actual worker namespace checks Git HEAD/cleanliness without `safe.directory`
exceptions, test interpreter version and installed pytest metadata, and whether
`git`, `gh`, and `hermes` are on PATH. Hermes/provider code is not executed. No model
requests or new full test run occur. Tool presence does not prove login support,
provider entitlement, dependency completeness, image credential absence or global
isolation. These and manager/App exclusive invocation remain separate gates.

An exclusive root-only intent is written before create. A returned exact container
ID is durably recorded and its image, label, mounts and confinement are verified
before start. A client timeout does not mean the container stopped: cleanup verifies
that same ID, kills it if running, verifies stopped, removes only it, then checks
absence. No forced removal, volume deletion, prune, Compose down or guessed-ID
cleanup. Lost create response or identity mismatch preserves the intent/container
for review; it never adopts a name/filter match as authority. Any prior probe intent
blocks a second invocation, even after successful cleanup.

Only after manager review/merge and exact-head CI, the canonical loader below
fetches the unchanged helper blob at an immutable source revision and verifies its
SHA256 before executing it. The manager supplies the private workspace value in
the user-facing command. No private path belongs in this repository.

```bash
python3 -I -B - "$EXISTING_PRIVATE_WORKSPACE" <<'PY'
import hashlib, signal, sys, urllib.request
source = '76a4b5f4dcf92ad57eae1c693aa2272ade10a8ab'
digest = '01361b11b151f7f61c2ad6c2a17ba9937dea0c61be25828ea120baf4aa476f16'
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): raise RuntimeError('redirect refused')
def expired(*_): raise TimeoutError()
signal.signal(signal.SIGALRM, expired)
signal.alarm(20)
try:
    url = 'https://raw.githubusercontent.com/aliercankonus/signal-desk-prediction/'+source+'/ops/bridge_one_shot/probe_worker_runtime.py'
    with urllib.request.build_opener(NoRedirect).open(url, timeout=15) as response:
        data = response.read(65537)
    if len(data) > 65536 or hashlib.sha256(data).hexdigest() != digest:
        raise RuntimeError('source digest mismatch')
except Exception:
    print('STOP: REVIEWED_PROBE_SOURCE_UNVERIFIED; preserve state; no retry')
    raise SystemExit(1)
finally:
    signal.alarm(0)
namespace = {'__name__':'reviewed_operator_probe'}
exec(compile(data, '<reviewed-worker-runtime-probe>', 'exec'), namespace)
sys.argv = ['probe', '--workspace', sys.argv[1], '--probe']
raise SystemExit(namespace['main']())
PY
```

The workspace variable is a private substitution made by the manager; do not ask
the operator to search for paths or construct another spec.

Expected `WORKER_RUNTIME: CAPABILITY_PASS` or `BLOCKED`, individual fixed PASS/FAIL
lines, `PROBE_CONTAINER: EXACT_ID_REMOVAL_VERIFIED`, and overall NO-GO. Missing tools
or declared-version mismatch are evidence to fix, never permission to install or
retry automatically. On STOP, timeout, interruption or absent cleanup confirmation:
preserve all files/intents, do not repeat, delete, clean, or switch attempts. Report
only the fixed sanitized receipt; never paste tokens/private state.

The frozen `operator_host.py --execute` entry remains blocked: it checks a now
worker-owned runner using root Git. A separately reviewed adapter must move that
check into the actual worker namespace before auth/task effects, preserving Git's
ownership protection and versioning source/manifests. This probe does not patch the
staged adapter or authorize that execution. #45 remains dormant; #44's portable
single application container/secured restore deliverable remains subsequent work.
