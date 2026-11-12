> **SUPERSEDED — DO NOT RUN ANY ENTRY BELOW.** Preserve both failed preparations. Use only the separately reviewed preparation-only [Git capture recovery v2](RECOVER_A2_OBJECT_CLONE_V2.md); it does not run a task or resume either old entry.

> **SUPERSEDED — DO NOT RUN THE TASK ENTRY BELOW.** The object-only source clone defect can leave a partial preparation. Preserve it; use only the separately reviewed preparation-only procedure in [RECOVER_A2_OBJECT_CLONE.md](RECOVER_A2_OBJECT_CLONE.md). That recovery does not authorize or resume a task.

# One separately approved #43 attempt: a2

Prepared source only. **Do not run the effectful block until Ali gives a new,
bounded approval in the manager conversation for this exact package.** The old
approval, cleanup receipt, this document, flags and GitHub comments are not new
runtime authority. The manager then publishes and independently reads the exact
new instruction and supplies its numeric ID. Ali does not construct a spec or
relay reports. No new instruction or grant is created by preparing/merging this
package.

## Scope to approve

Exactly one fresh Bridge attempt for the frozen #43 English Markdown artifact,
`docs/ONE_SHOT_REVIEW_NOTE.md`, with the original test/private interpreter
contract. The native child may edit/test/commit/push only that artifact. Bridge
owns one draft PR; it cannot merge or deploy. Use branch `issue43-one-shot-a2`, a
fresh queue UUID and Bridge run UUID, fresh clone/state/inbox/journals and policy
identity `1da74bf1d715dc3c0a78809955a2401744e85f64014bdbb57a1e9626e001c037`.

Legacy runner pin `00acd27132b68264ee2ab1692d3024f09c640c6d` and the separately
reviewed candidate `e84021a786004456a12de9e25eae50d191da6cf1` are unchanged.
Frozen adapter `eac843de7967d48cce56ee9a198750e98754a2de` and the installed v2
bundle remain unchanged. The new independently versioned overlays are loaded
only from verified root source/read-only helper binds. This is not installation
of today's dormant overlay into the old consumed run.

The consumed queue `2f175fc762d5476c8938472c7f784094` and run
`a4db0f8a32ea451ab0ae0e1aa55ba768` are never continued. Old source refs, runner,
worktree, claims, inbox/history, auth home, credentials, configuration and venv
are retained. The new worker reuses existing protected auth/context/venv and
read-only token binds; there is no credential creation or device login. Root validates the reused token file metadata and device-only public config
before a bind; it does not read token/provider auth-store contents. Normal worker auth use remains part
of the separately approved one model attempt.

## Changes and failure boundaries

The exact worktree comes from the existing durable BridgeQueue allocation:
`/state/queue/<queue_id>/bridge/worktrees/<run_id>`. Reuse the reviewed
`queued_write_root.py` scope around that Bridge instance. The worker receives a
sentinel write root before allocation; the overlay scopes only the actual one
worktree and restores its environment even after failure.

The frozen outer process-group supervisor still owns descendant termination and
reaping, with a 630-second child limit, 12 turns and a 600-second run budget. The
root runtime lifecycle is bounded to 1800 seconds, with a pre-claim time reserve.
The new capture wrapper does not create another session/process group. It adds
explicit `--provider openai-codex`; installed chat help must advertise that flag
before signing/dispatch. CLI support is not an inference/entitlement claim.

Raw stdout is discarded. At most 8192 stderr bytes remain transiently in worker
memory; raw output is never saved or posted. A private, exclusive intent and exit
receipt carry queue/run IDs, numeric exit/signal/duration/byte count and a fixed
observed-pattern enum. An HTTP pattern is not a verified quota/provider cause.
Root binds this evidence to the actual queue mapping and publishes only that
bounded projection. If the child is killed before a receipt, evidence remains
missing/uncertain. No automatic second invocation follows either state.

The exact new instruction is read again before signing; same-account comments,
commits and arbitrary reports cannot become tasks. The existing signature,
durable signer claim, inbox claim, mutex, publication intent and queue fences
remain. An edited instruction, changed #43 body, any existing new-branch ref or
PR (including closed PR history), existing attempt directory or unknown claim
refuses. Private plan/scope are generated from the preserved verified plan;
there is no manual spec editing. Manager App metadata alone still does not prove
exclusive App invocation; root/operator protection and this exact one-ID handoff
are necessary. It is not a general autonomous signer enrollment.

A normally returned durable blocked claim with resolved receipt publication can
proceed to the already-reviewed exact root-only runtime cleanup. Unknown claim,
ambiguous signing/publication/effect or changed identity stays preserved. Cleanup
uses only the exact recorded containers/networks and scoped SD_ONCE rules; no
worker cleanup code or guessed IDs. Root-only intents are fsynced. Old records
and new queue/worktree/claim are retained; an enabled inbox flag is inert once
its exact containers are gone. A success claim requires independent root GitHub
artifact/branch/draft/receipt readback. Exact-head CI is reported as observed;
the manager separately checks its eventual result before any suitable merge.

## Immutable entry and manifest

Source commit: `c12a60ca1c265e4b7085027bf809234367db07b2`.

- `attempt_a2.py` SHA256: `211867c828edc0d18f493790665c688c90edcd3d0cf6246b8ae47e099ed2ca54`
- `release_a2.json` SHA256: `88fc917ddd132bfed497216c97df35a9f025d5c0cc56b0cbbb8b03a51e61e353`

The source entry and manifest pin all root/worker dependencies. Defaults are
review-only with no host/network/task action. The following block is reserved
for the **new explicitly approved operator handoff**, on the existing VPS root
terminal. It prompts privately for the existing protected setup workspace and
for the exact numeric instruction ID supplied by the manager after approval.
Do not paste a token or auth store. No install/enrollment timer is included.

```bash
(
set -euo pipefail
test "$(id -u)" -eq 0 && test -t 0
read -r -p 'Existing protected setup workspace (absolute path): ' A2_WORKSPACE
read -r -p 'Exact newly approved manager instruction ID: ' A2_INSTRUCTION
python3 -I -B -c '
import hashlib,re,signal,sys,urllib.request
commit="c12a60ca1c265e4b7085027bf809234367db07b2"
expected="211867c828edc0d18f493790665c688c90edcd3d0cf6246b8ae47e099ed2ca54"
manifest="88fc917ddd132bfed497216c97df35a9f025d5c0cc56b0cbbb8b03a51e61e353"
workspace,instruction=sys.argv[1:]
if not re.fullmatch("[1-9][0-9]{0,19}",instruction):raise SystemExit("STOP: instruction ID")
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*a,**kw):raise RuntimeError("redirect refused")
def timeout(*a):raise TimeoutError()
signal.signal(signal.SIGALRM,timeout);signal.alarm(20)
try:
    url="https://raw.githubusercontent.com/aliercankonus/signal-desk-prediction/"+commit+"/ops/bridge_one_shot/attempt_a2.py"
    with urllib.request.build_opener(NoRedirect).open(url,timeout=15) as response:data=response.read(65537)
finally:signal.alarm(0)
if not data or len(data)>65536 or hashlib.sha256(data).hexdigest()!=expected:raise SystemExit("STOP: entry digest")
sys.argv=["attempt_a2.py","--workspace",workspace,"--release-commit",commit,"--release-sha256",manifest,"--instruction-id",instruction,"--execute-new-approved-attempt"]
exec(compile(data,"<immutable-a2-entry>","exec"))
' "$A2_WORKSPACE" "$A2_INSTRUCTION"
)
```

Expected successful outcome: one new draft PR for the exact artifact, a root
readback/cleanup report posted and read back in #41, `OWN_RUNTIME_CLEANUP:
EXACT_IDS_VERIFIED`, original history preserved and `HOURLY_TIMER: NOT_INSTALLED`.
A blocked result is not success. Any STOP or ambiguous cleanup/report means
preserve all files/resources and do not repeat this or any old task/auth/cleanup
entry. The manager reads GitHub receipts directly and owns further preparation.

## Remaining acceptance and portability

Offline tests cannot prove actual cross-UID transfer, image/host isolation,
provider inference, GitHub write entitlement, a successful first real loop or
an installed watcher. The old exit-1 cause is unknown. No elapsed-time quota
inference is valid. #41/#43/#45 remain open until their real acceptance gates
pass. The :30 Europe/Amsterdam scheduler remains dormant; minute :00 manager
checks are scheduling targets, not guaranteed liveness. A successful bounded
attempt does not authorize another task or enable a timer.

#44 remains the subsequent clean-host restore/portable application deliverable.
This package records successful public setup/procedure/test source durably; it
does not claim the existing image/private venv or the current worker/proxy pair
is a portable single application container. That future deliverable still needs
immutable build inputs, one entry command and separately secured persistent
state backup/restore. No credentials, auth stores or raw private state belong in
GitHub.
