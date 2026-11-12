# Preparation-only a2 Git capture recovery v2

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

## Additional v1 defect and prerequisite

The v1 recovery is withdrawn too. Its global `RLIMIT_FSIZE(65536)` applied to
Git object/pack files, not just captured stdout. A real 256KiB incompressible
object reproduced clone exit 128 with the target removed; normal Git succeeds.
The latest operator reports source bare/object checks succeed and the v1 new
runner is absent. This matches the new regression but is not independent proof
of the exact historical VPS error, whose stderr was discarded.

V2 removes the GLOBAL file-size limit. A selector drains stdout into a 64KiB
bounded buffer and stderr into a transient 8KiB tail. No raw stderr is persisted
or printed. The Git subprocess and descendants use an owned process group;
WNOWAIT retains the PID until group termination/reaping on exit/error/timeout.
The controlled failure code now includes the exact Git operation. A process
output bound cannot limit pack/object/index/worktree file sizes.

V2 requires the preserved `object-clone-recovery-01` directory to contain exactly
the original preparation intent and the recorded `exact-object-clone` Stop
receipt, with NO runner/ready/report or other files. Both files are included in
the preservation snapshot. It creates a different recovery-02 directory; it
does not resume/reset or clean recovery-01. Unknown old progress refuses before
new effects. The current failed task/staging entry must never be repeated.

## Behavior and preservation

The entry validates the fixed a2 stage instruction/policy, root-private workspace
and old plan, empty queue/journals, absent stage-ready/plan/runtime/inbox and absent
signer claim for instruction 6824067293. It refuses an advanced or uncertain
attempt. It snapshots the bounded nonsecret prefix, creates the exclusive
`object-clone-recovery-02` intent directory, and never resets or resumes it.
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
deployment, task or timer action is present. Provider auth stores, signing keys and the
venv are not inspected. The a2 token placeholder must still be empty; snapshot
refuses a nonempty token or unexpected auth file BEFORE reading it.

With `--report`, only the existing root GitHub reporting credential is read, for
one POST and exact GET readback in #41. It is not provisioned or copied. An
exclusive report intent precedes the request; a lost response is preserved with
no retry. No private paths, raw files or token values enter that report. GitHub
reports preparation only, not runtime isolation, entitlement or first-loop success.

## Immutable operator entry

Source: `c740da7fd33264a80e891b8bc6397a6e81be75fb`.
SHA256: `df8834dd948a32845a4e2451774ebb98758888c3b9c678087b0338b15ca06387`.

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
commit="c740da7fd33264a80e891b8bc6397a6e81be75fb"
expected="df8834dd948a32845a4e2451774ebb98758888c3b9c678087b0338b15ca06387"
workspace=sys.argv[1]
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*a,**kw):raise RuntimeError("redirect refused")
def timeout(*a):raise TimeoutError()
signal.signal(signal.SIGALRM,timeout);signal.alarm(20)
try:
    url="https://raw.githubusercontent.com/aliercankonus/signal-desk-prediction/"+commit+"/ops/bridge_one_shot/prepare_a2_object_clone_v2.py"
    with urllib.request.build_opener(NoRedirect).open(url,timeout=15) as response:data=response.read(65537)
finally:signal.alarm(0)
if not data or len(data)>65536 or hashlib.sha256(data).hexdigest()!=expected:raise SystemExit("STOP: entry digest")
sys.argv=["prepare_a2_object_clone_v2.py","--workspace",workspace,"--prepare","--report"]
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
