# Exact runtime cleanup of the consumed #43 attempt

[Diagnostic 6778310463](https://github.com/aliercankonus/signal-desk-prediction/issues/41#issuecomment-6778310463)
is operator-produced host evidence: queue invocation count 1, child exit 1 after
19067 ms, last confirmed checkpoint worktree-created, no recorded head/PR,
and unresolved cleanup. It is not direct manager host execution, proof of
quota/provider cause, or proof that no unrecorded task/Git effect occurred.

The original user approval for the one-shot includes cleanup of its exact owned
runtime. This operator entry completes only that boundary; it does not reuse
that approval for another task, login, credential provisioning, model request,
signing, grant, enqueue, retry, deployment, timer or historical recovery.
An approval flag or issue prose is not independent authority. Automation never
runs this on the host. The root operator invokes this reviewed command once.

The entry requires the successful diagnostic receipt to match its exact fixed
queue/run and the current structured diagnostic bytes. It verifies all frozen
root helper digests; the complete original root-owned resource journal; the
blocked worker claim; actual Docker image, UID, capabilities, namespaces,
read-only rootfs, mounts, environment names and exact network peers; and the
reviewed scoped firewall with no unrelated references. Root keys/auth stores
are not inspected. The existing root GitHub reporting credential is used only
for the final sanitized report.

After all metadata gates, it creates a fresh one-use root cleanup directory and
fsyncs identity/baseline/intents before effects. It stops/verifies/removes only
the recorded worker ID, rolls back only the reviewed SD_ONCE rules, then stops/
verifies/removes only the recorded proxy ID and removes their exact empty,
validated networks. It compares all unrelated container/network IDs before and
after. Concurrent resources, changed metadata or ambiguous effects stop the
procedure; there is no automatic retry, guessed removal, compose down, global
firewall flush, Docker socket mount or broad host access.

It never executes worker code, even to disable intake. After exact containers
are gone the preserved enabled inbox flag has no installed consumer; its blocked
claim prevents dispatch by the existing inbox anyway. The original phase.json,
claim/inbox bytes, queue/worktree, auth/home, source refs, private venv, signer
history and all prior journals are preserved. A separate cleanup receipt does
not clear the task's unresolved-effect record or authorize continuation.
Transient owned container/tmpfs/network resources are removed; persistent bind
mounts survive. The cleanup records raw IDs only in root-private metadata and
publishes only fixed counts/booleans/public task identities to #41 with an exact
readback. An uncertain report POST is not retried.

Run only after source review, exact-head CI and merge:

```bash
(
read -r -p 'Existing absolute private setup workspace: ' SD_SETUP_WORKSPACE </dev/tty
export SD_SETUP_WORKSPACE
python3 -I -B - <<'PY'
import hashlib, os, pathlib, subprocess, tempfile, urllib.request
if os.geteuid() != 0:
    raise SystemExit('STOP: ROOT_OPERATOR_REQUIRED')
workspace = os.environ.get('SD_SETUP_WORKSPACE', '')
if not workspace.startswith('/') or '..' in pathlib.Path(workspace).parts:
    raise SystemExit('STOP: WORKSPACE_REQUIRED')
url = ('https://raw.githubusercontent.com/aliercankonus/signal-desk-prediction/'
       'dac9749cd6b2f58f0d0f9ce7d1d9092ef1d1c1af/'
       'ops/bridge_one_shot/cleanup_consumed_issue43.py')
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise RuntimeError('redirect denied')
try:
    with urllib.request.build_opener(NoRedirect).open(url, timeout=20) as response:
        data = response.read(65537)
    if not data or len(data) > 65536 or hashlib.sha256(data).hexdigest() != '819333dbcd88d7b077fb3d1550656096423560de9a2ce77bb46c1b8322f8a18e':
        raise RuntimeError('immutable source digest mismatch')
    folder = pathlib.Path(tempfile.mkdtemp(prefix='signal-desk-issue43-cleanup-', dir='/root'))
    path = folder / 'cleanup_consumed_issue43.py'
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    result = subprocess.run(['python3', '-I', '-B', str(path),
        '--workspace', workspace, '--cleanup'], check=False)
    if result.returncode:
        raise SystemExit('STOP: EXACT_CLEANUP_PRESERVE_STATE; no retry')
except Exception:
    raise SystemExit('STOP: CLEANUP_ENTRY_PRESERVE_STATE') from None
PY
)
```

Expected: `OWN_RUNTIME_CLEANUP: EXACT_IDS_VERIFIED`,
`HISTORY_AUTH_CLAIM: PRESERVED`, and `GITHUB_CLEANUP_REPORT: <comment-id>`.
Manager reads the result directly on GitHub. Any STOP or partial intent means
preserve files/resources; do not repeat, erase the marker, or run an old task
entry. A missing resource is a reconciliation boundary, not a removal guess.

## Dormant write-root correction

`ops/github_inbox/queued_write_root.py` is a separately reviewed factory overlay
for a future explicitly authorized attempt. It derives the exact child worktree
from the actual durable BridgeQueue entry, then scopes HERMES_WRITE_SAFE_ROOT to
that directory only while the original frozen Bridge.once runs. It restores the
previous environment on success or exception. The regression allocates a real
entry through BridgeQueue.enqueue from a local Git fixture, proves the old root
does not contain the allocated worktree and verifies the new root does. No model
or production task runs in this test.

The overlay is not installed or wired into the consumed #73 entry; no runner,
loader source or historical pin is changed. It does not recover/retry this run
or establish the cause of exit 1. Any future attempt needs a new reviewed run
identity/authority after read-only Git/remote/provider reconciliation. #45 :30
Europe/Amsterdam timer remains dormant; #44 single-container/secured restore
remains subsequent. Today's one-shot is not a portable application container.
