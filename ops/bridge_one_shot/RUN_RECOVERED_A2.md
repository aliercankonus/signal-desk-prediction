# Recovered a2 one-shot root entry

This versioned caller uses the already-recorded bounded approval for exactly
instruction 6824067293 and frozen #43 artifact scope. It is not a new task,
permission from issue prose/flags, or authority for manager automation to run the
host. Only the operator may invoke the reviewed immutable handoff after manager
review/CI; no entry is run during source preparation or merge.

The previously consumed original #43 run stays consumed. The a2 task has not
been signed/dispatched by the recovery procedures. The caller requires its exact
signer claim absent, queue/journals empty and no inbox/advanced stage. It reads
recovery-02 ready/local report-intent/report-receipt, independently verifies
GitHub preparation receipt 6825239944, old plan transition, preserved prefix and
source refs, worker-owned detached HEAD and exact original instruction/task/
policy/scope. It refuses any existing integration directory, new task branch or
matching PR history. No source/recovery/task entry is reset or repeated.

All dependencies are hash-verified public immutable source, including frozen a2
release, recovery-v2, binding gate and root bundle lifecycle/host modules. No root
code is imported from the writable worker checkout. The existing token source
is checked by metadata only and device-only public config is rechecked before
binds; no credential provisioning or provider login occurs. Existing auth/home/
context/venv/pins and every old prefix/claim/history are retained. Legacy runner
00acd27132b68264ee2ab1692d3024f09c640c6d and separately reviewed candidate
e84021a786004456a12de9e25eae50d191da6cf1 remain unchanged.

Only a new root-private `issue43-a2-integration-01` directory is created. Its
exclusive fsynced intent precedes helper/plan/journal creation. Only immutable
public capture/factory/write-root helpers are copied; credentials are not copied.
The read-only proposal adapter accepts Git's normal recovered top-directory
0755 only for the exact worker-owned recovery-02 runner beneath its verified
root-private parent. It does not change the real host validator. After the new
integration intent is durable, an inode-bound no-follow descriptor tightens ONLY
that new runner top directory to 0700; files, old runners and ownership are not
changed. Other modes/owners/symlinks refuse. The unchanged real host preflight
still requires its original strict private-directory rules.
The frozen lifecycle uses a new journal and mandatory worker owner/Git clean/
CLI/context preflight, authenticated read-only checks, one exact signature/grant,
one Bridge claim and independent root artifact/draft/CI readback. The native
child is limited to 12 turns, a 600-second budget and 630-second process-group
supervision; root runtime remains bounded to 1800 seconds. Existing explicit
openai-codex selection/help gate and exact allocated worktree mapping remain.

Known returned blocked claims can receive exact owned-runtime cleanup. Uncertain
startup/claim/publication stays preserved; no guessed cleanup or automatic retry.
SIGTERM enters the frozen lifecycle's interruption handling. No broad SSH, Docker
socket mount, migration/deletion, trading or persistent service/timer is added.
A successful run reports its exact cleanup/readback to #41. CI observations may
still be pending; manager must independently verify exact-head completion before
any suitable task PR merge. A GitHub receipt is operator-produced host evidence,
not direct manager observation of the VPS. An observed stderr pattern is not a
verified quota/provider cause. Provider entitlement, image/host isolation,
manager-exclusive App invocation and first actual loop are not proven offline.

## Immutable operator handoff

Source `87f99921d862b272a2e8c36121df97862959f6ba`.
Entry SHA256 `563fe7cff46756c89aca875495ed0c7ed8f5caedad728835936dbab97af4efe1`.

Run only once in the existing VPS root terminal. No manual spec or report relay.
The default source entry is inert; the explicit flag below selects only the
previously approved, unclaimed instruction. Stop if its scope is no longer valid.

```bash
(
set -euo pipefail
test "$(id -u)" -eq 0 && test -t 0
read -r -p 'Existing protected setup workspace (absolute path): ' RECOVERED_WORKSPACE
python3 -I -B -c '
import hashlib,signal,sys,urllib.request
commit="87f99921d862b272a2e8c36121df97862959f6ba"
expected="563fe7cff46756c89aca875495ed0c7ed8f5caedad728835936dbab97af4efe1"
workspace=sys.argv[1]
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*a,**kw):raise RuntimeError("redirect refused")
def timeout(*a):raise TimeoutError()
signal.signal(signal.SIGALRM,timeout);signal.alarm(20)
try:
    url="https://raw.githubusercontent.com/aliercankonus/signal-desk-prediction/"+commit+"/ops/bridge_one_shot/run_recovered_a2.py"
    with urllib.request.build_opener(NoRedirect).open(url,timeout=15) as response:data=response.read(65537)
finally:signal.alarm(0)
if not data or len(data)>65536 or hashlib.sha256(data).hexdigest()!=expected:raise SystemExit("STOP: entry digest")
sys.argv=["run_recovered_a2.py","--workspace",workspace,"--execute-approved-once"]
exec(compile(data,"<immutable-recovered-a2-entry>","exec"))
' "$RECOVERED_WORKSPACE"
)
```

Expected: `RECOVERED_A2_RESULT: review-ready`, `CLEANUP_VERIFIED: True` and a
`GITHUB_REPORT` ID; manager reads GitHub receipts directly. A blocked or STOP
result is not success. Preserve every file/resource and do not repeat any entry,
clear intents, change permissions or guess cleanup. The controlled phase/type
marker never prints raw private failure text.

#45 :30 Europe/Amsterdam scheduler remains uninstalled/dormant; this is only one
approved task roundtrip. It does not authorize another task or timer. #44 portable
single-application-container/clean-host restore remains subsequent; today's image,
private venv and worker/proxy pair are not claimed portable. All nonsecret source,
tests and the successful public procedure belong in reviewed repository files;
no auth stores, credentials or raw private state belong in GitHub.
