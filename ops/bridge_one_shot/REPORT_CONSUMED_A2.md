# One-use read-only consumed a2 diagnostic

This entry inspects ONLY the consumed queue7859a7198b8948ce953c1759feb106ce /
run2a07298e691f47558826903aef0b2a3d. It binds the protected integration plan,
blocked/cleaned lifecycle journal and native receipt to authenticated GitHub
cleanup report6827131876, then projects bounded SQLite stages/failure/head/PR
presence and recovery checkpoint enums. It never runs Git, Docker, a model,
provider login/auth-store read, signer/grant, enqueue, task, cleanup or timer.
Historical stdout was discarded: the precise CLI/provider cause may remain
unknown. This is not quota/entitlement or first-loop evidence.

Root source and diagnostic/signer-library dependencies are immutable/hash-checked
before import. Signer methods are not invoked: only the existing root GitHub
reporting token is used for a bounded report GET/POST/readback in #41. No token,
raw context, private path, raw exception or stream output enters the report.
No provider store/signing key is opened. Queue/DB/checkpoint reads enforce exact
IDs/owner/mode/inode, no symlinks/hardlinks/sidecars, immutable query-only SQLite,
extensions disabled and bounded file/row/query work. Any changed/uncertain state
refuses. Files inspected are never modified; no permission changes occur.

With --report, a fresh root-private issue43-a2-diagnostic-01 directory records an
exclusive fsynced publication intent before one POST, then exact GET readback.
Existing/partial intent refuses; a lost reply is preserved, never retried.
Defaults do nothing. The separate dual-stream capture remains dormant/uninstalled.
Both historical task approvals are consumed; no diagnostic result authorizes a
new model attempt. Never repeat #80 or any task/recovery entry.

Source: `9f8114b17d4019a86589db954220cf7fa48c5672`.
SHA256: `005cbcb629c755a4365ae86aad5027becee504b8ac7217c74f6b1da4a96f9c04`.

Run the reviewed handoff once on the existing VPS root terminal. No manual spec,
private log or report relay. Only the new diagnostic publication journal is
created; all original worktrees/claims/auth/journals remain preserved.

```bash
(
set -euo pipefail
test "$(id -u)" -eq 0 && test -t 0
read -r -p 'Existing protected setup workspace (absolute path): ' DIAG_WORKSPACE
python3 -I -B -c '
import hashlib,signal,sys,urllib.request
commit="9f8114b17d4019a86589db954220cf7fa48c5672"
expected="005cbcb629c755a4365ae86aad5027becee504b8ac7217c74f6b1da4a96f9c04"
workspace=sys.argv[1]
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*a,**kw):raise RuntimeError("redirect refused")
def timeout(*a):raise TimeoutError()
signal.signal(signal.SIGALRM,timeout);signal.alarm(20)
try:
    url="https://raw.githubusercontent.com/aliercankonus/signal-desk-prediction/"+commit+"/ops/bridge_one_shot/report_consumed_a2.py"
    with urllib.request.build_opener(NoRedirect).open(url,timeout=15) as response:data=response.read(65537)
finally:signal.alarm(0)
if not data or len(data)>65536 or hashlib.sha256(data).hexdigest()!=expected:raise SystemExit("STOP: entry digest")
sys.argv=["report_consumed_a2.py","--workspace",workspace,"--inspect","--report"]
exec(compile(data,"<immutable-consumed-a2-diagnostic>","exec"))
' "$DIAG_WORKSPACE"
)
```

Expected GITHUB_A2_DIAGNOSTIC_REPORT ID and A2_DIAGNOSTIC COMPLETE, consumed
state preserved, no model/task/runtime action. Manager reads the report directly.
On STOP preserve all state and do not rerun, remove an intent or guess cleanup.
Offline fixtures do not prove actual root/worker ownership/VPS health; the posted
result is operator-produced evidence. A later real attempt needs a complete
reviewed revised package/fresh identities and NEW explicit bounded approval.
#45 :30 remains uninstalled/dormant; #44 portability remains subsequent.
