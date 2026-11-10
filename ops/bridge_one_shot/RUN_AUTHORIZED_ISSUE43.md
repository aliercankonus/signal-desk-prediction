# One approved #43 task, reusing the authenticated worker

Ali explicitly approved the single frozen #43 documentation task, bounded model
use, tests, one commit/push and Bridge-owned draft PR/CI in the manager
conversation. The approval is recorded in [#41 comment 6775491461](https://github.com/aliercankonus/signal-desk-prediction/issues/41#issuecomment-6775491461).
Only [instruction 6775497757](https://github.com/aliercankonus/signal-desk-prediction/issues/41#issuecomment-6775497757)
is accepted. That exact immutable comment, actor, App provenance and policy hash
are checked; the shared GitHub account/App alone is not manager exclusivity.
This file is a procedure, not evidence that a VPS operation ran.

Run the block only once from the operator's VPS root terminal, after manager
review, exact-head CI and merge. Supply the existing private setup workspace
when prompted; no manually constructed spec or additional device login is needed.
The public helper files are downloaded to a fresh root-private directory,
verified before import, and preserved. The known auth helper is reused solely
for confinement and public verification functions, never its consumed auth entry.

This operation starts a temporary isolated worker/proxy and scoped firewall
backstop, reuses the successful dedicated auth home, validates actual CLI flags,
local backend, immutable test interpreter/context and Git scope before signing,
then enrolls a disabled inbox from the original explicitly reviewed cursors.
The frozen latest-comment enrollment would otherwise skip the approved
instruction and fail its own root cursor check. This wrapper supplies the
explicit original cursor snapshot and gives the inbox only the exact newly
verified signed grant. Existing signature, no-replay claim, mutex, queue and
Bridge publication checks remain active. No arbitrary commit/comment or other
same-account instruction can become a task through this entry.

The only new application artifact is `docs/ONE_SHOT_REVIEW_NOTE.md`, exactly as
frozen in #43, branch `issue43-one-shot-review-note`, base/candidate runner
`e84021a786004456a12de9e25eae50d191da6cf1`. Historical runner pin
`00acd27132b68264ee2ab1692d3024f09c640c6d` and adapter pin
`eac843de7967d48cce56ee9a198750e98754a2de` remain preserved.
Worker checkout, task state and its existing home are writable; authorization,
context, verifier, venv and helper binds are read-only. Generic file writes are
limited to `/state/worktrees`; this tool setting is not the security boundary.
Docker namespaces, exact mounts, UID/capabilities and restricted proxy/network
provide the reviewed process boundary. No root signing key is worker-mounted.

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
    raise SystemExit('STOP: EXISTING_WORKSPACE_REQUIRED')
entries = (
    ('09aa854e8e1751f62286c0c1fc686a634d299729',
     'ops/bridge_one_shot/run_authorized_issue43.py',
     '374d1799d2b63488fc77811e87d659d574fb8660d6735c37d7c0855f63591ee9'),
    ('5d1a005ae3a3a5816fd94ae085d6d81797e4cdf6',
     'ops/bridge_one_shot/authenticate_worker_clone_fix.py',
     '405e3a9ce73cf22403ea9d75a976df920cc99c1517b057749caa9681434f4b84'),
)
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise RuntimeError('redirect denied')
folder = pathlib.Path(tempfile.mkdtemp(prefix='signal-desk-issue43-entry-', dir='/root'))
try:
    for commit, name, digest in entries:
        url = 'https://raw.githubusercontent.com/aliercankonus/signal-desk-prediction/' + commit + '/' + name
        with urllib.request.build_opener(NoRedirect).open(url, timeout=20) as response:
            data = response.read(65537)
        if not data or len(data) > 65536 or hashlib.sha256(data).hexdigest() != digest:
            raise RuntimeError('immutable source digest mismatch')
        path = folder / pathlib.Path(name).name
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
    with open('/dev/tty', 'rb', buffering=0) as terminal:
        result = subprocess.run(['python3', '-I', '-B', str(folder / 'run_authorized_issue43.py'),
            '--workspace', workspace, '--auth-helper', str(folder / 'authenticate_worker_clone_fix.py'),
            '--execute-approved-issue43'], stdin=terminal, check=False)
    if result.returncode:
        raise SystemExit('STOP: ISSUE43_PRESERVE_STATE; no retry or guessed cleanup')
except Exception:
    raise SystemExit('STOP: ENTRY_PRESERVE_STATE; no retry, overwrite or cleanup') from None
PY
)
```

Expected: `ISSUE43: REVIEW_READY`, `OWN_RUNTIME_CLEANUP: EXACT_IDS_VERIFIED`,
a verified GitHub report ID and `HOURLY_TIMER: NOT_INSTALLED`. The draft PR and
its exact head/CI remain subject to independent manager GitHub review; pending
CI is not a passed check. Login success alone never proved model entitlement.

Any STOP, blocked claim, timeout, partial resource identity, ambiguous push/POST,
quota or crash means preserve all state and do not run the block again. The
controller exposes only fixed failure phase/code, never private output. Exact
owned cleanup is attempted only when identities and effect completion are known;
unknown effects are preserved for read-only manager reconciliation. Do not
remove files/resources to make a second attempt possible. Original staging,
auth01/auth02 history, successful provider home and signer/queue history survive.

No persistent worker, service or hourly timer is installed. The :30
Europe/Amsterdam #45 schedule remains dormant; it needs separate runtime
approval after the first reviewed loop. #44 single-container portability and
clean-host secured backup/restore remain the subsequent deliverable. Today's
isolated multi-container one-shot is not that portable application.
