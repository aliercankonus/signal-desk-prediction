# Preparation-only a2 object-store recovery

The earlier a2 task entry is withdrawn after a source-preparation STOP. Do not
repeat that entry, remove its partial runner, change ownership, clear an intent
or dispatch a task. No exact host failing command is claimed: operator metadata
shows the helper/policy prefix and a root-owned partial clone, with no stage-ready,
plan, runtime config or lifecycle phase journal. The source defect is independently
reproduced offline: an object-only bare store may contain the exact commit but
have no refs; clone succeeds without transferring the object and checkout fails.

This reviewed replacement prepares ONE new runner beside that prefix. It does
not finish the old staging procedure or resume its lifecycle. The original
`attempt_a2.py` and its pinned release remain historical source; do not invoke
it against either clone. A separately reviewed integration must use the recovered
runner before any future task continuation is proposed.

## Behavior and preservation

The entry validates the fixed a2 stage instruction/policy, root-private workspace
and old plan, empty queue/journals, absent stage-ready/plan/runtime/inbox and absent
signer claim for instruction 6824067293. It refuses an advanced or uncertain
attempt. It snapshots the bounded nonsecret prefix, creates the exclusive
`object-clone-recovery-01` intent directory, and never resets or resumes it.
The existing partial runner is not executed, modified, deleted or chowned.

The source is the existing root-protected LOCAL bare store from the preserved
plan, not a network remote. Root Git clones into a new directory and fetches ONLY
candidate pin `e84021a786004456a12de9e25eae50d191da6cf1` using
`--no-write-fetch-head --no-tags`, with no destination refspec. It checks HEAD,
cleanliness, source refs/HEAD/FETCH_HEAD/config preservation and no new FETCH_HEAD,
then transfers only the NEW runner to UID:GID 10000:10000. No root Git operation
follows ownership transfer; no safe.directory bypass is used. Each Git process
has a 45-second cap inside a 600-second clone deadline and bounded public output.
Legacy runner pin `00acd27132b68264ee2ab1692d3024f09c640c6d` remains unchanged.

A final prefix comparison precedes a root-only ready receipt. Failure leaves the
new intent/partial clone and a bounded stage/exception-type receipt, never raw
stderr. Any existing recovery directory refuses before a second clone. No
signer/grant, model, auth provisioning/login, Docker/network/firewall, cleanup,
deployment, task or timer action is present. Old auth home/key/token stores and
venv are not inspected. The a2 token placeholder must still be empty; snapshot
refuses a nonempty token or unexpected auth file BEFORE reading it.

With `--report`, only the existing root GitHub reporting credential is read, for
one POST and exact GET readback in #41. It is not provisioned or copied. An
exclusive report intent precedes the request; a lost response is preserved with
no retry. No private paths, raw files or token values enter that report. GitHub
reports preparation only, not runtime isolation, entitlement or first-loop success.

## Immutable operator entry

Source: `08cb8d9a965c5dce4211c88126cf203b4a63f8a9`.
SHA256: `380e1b0e940c459c688f98e6cb8e6e654eecf48e4300fd7234781b77073c3831`.

Run once in the existing VPS root terminal. Supply the existing protected setup
workspace; do not create a spec, paste a credential, repeat an old command or
change the old runner. This entry is preparation/reporting only; it cannot run
the approved artifact task or activate the :30 scheduler.

```bash
(
set -euo pipefail
test "$(id -u)" -eq 0 && test -t 0
read -r -p 'Existing protected setup workspace (absolute path): ' RECOVERY_WORKSPACE
python3 -I -B -c '
import hashlib,signal,sys,urllib.request
commit="08cb8d9a965c5dce4211c88126cf203b4a63f8a9"
expected="380e1b0e940c459c688f98e6cb8e6e654eecf48e4300fd7234781b77073c3831"
workspace=sys.argv[1]
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*a,**kw):raise RuntimeError("redirect refused")
def timeout(*a):raise TimeoutError()
signal.signal(signal.SIGALRM,timeout);signal.alarm(20)
try:
    url="https://raw.githubusercontent.com/aliercankonus/signal-desk-prediction/"+commit+"/ops/bridge_one_shot/prepare_a2_object_clone.py"
    with urllib.request.build_opener(NoRedirect).open(url,timeout=15) as response:data=response.read(65537)
finally:signal.alarm(0)
if not data or len(data)>65536 or hashlib.sha256(data).hexdigest()!=expected:raise SystemExit("STOP: entry digest")
sys.argv=["prepare_a2_object_clone.py","--workspace",workspace,"--prepare","--report"]
exec(compile(data,"<immutable-object-clone-recovery>","exec"))
' "$RECOVERY_WORKSPACE"
)
```

Expected output: `GITHUB_PREPARATION_REPORT: <id>` followed by
`A2_RUNNER_RECOVERY: PREPARED_ONLY; OLD_PREFIX: PRESERVED;
TASK_RUNTIME_SIGNING_TIMER: NOT_STARTED`. The manager reads the GitHub receipt;
Ali need not relay reports. On any STOP, do not repeat, delete or guess cleanup.
A ready runner is not an installed inbox or completed task. #41/#43/#45 remain
open; #44 single-container/clean-host portability is subsequent. Offline Git and
fixture tests do not prove actual root-to-worker ownership transfer or VPS health.
