# Inspect the consumed #43 run and report on GitHub

This is a diagnostic entry, not task continuation or cleanup permission. The
operator reported #73 blocked with cleanup/report unverified. GitHub independently
shows grant 6777657372, queue `2f175fc762d5476c8938472c7f784094`, and
blocked #43 run `a4db0f8a32ea451ab0ae0e1aa55ba768`. The blocked status does not
establish model quota, entitlement, push outcome or resource cleanup.

The manager found a concrete source defect in #73: `/state/worktrees` does not
contain `/state/queue/<queue-id>/bridge/worktrees/<run-id>`. The actual run's
structured failure category is still required before attributing the stop to
that defect. Preserve the consumed grant, claim, queue, worktree, provider home,
signer journal and all resources. Do not rerun the task entry, login, enqueue,
reset a claim, remove containers or clean files.

After manager review, exact-head CI and source merge, run this block once from
the VPS root terminal. Supply the existing private setup workspace when prompted.
It downloads and verifies only public code, reads only fixed lifecycle/queue/
SQLite diagnostic/checkpoint fields, and emits only allowlisted enums, bounded
numbers, public run identities and a safe-root containment boolean. No raw
exception/log/session text, private path, credential label, prompt or environment
value is published. SQLite is opened read-only/immutable with schema trust off,
row/size/execution bounds and change/sidecar checks; no worker code is imported
as root. A live/changed/unsafe database refuses inspection.

With `--report`, it reads the existing root reporting credential through the
hash-verified, previously reviewed root GitHub client and posts/readbacks one
sanitized #41 comment. A root-private report intent is fsynced before any POST;
an existing intent refuses replay even after a failed or ambiguous POST. This
uses the already authorized task's reporting boundary, not new task authority.
There is no Docker/Git subprocess, cleanup, model/provider call, signing,
enrollment, timer or real dispatch. Runtime process/container state remains
UNVERIFIED; a database failure receipt is not proof of process termination.

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
       '1712083e1cc5d576111695e0c26381fdb32c4245/'
       'ops/bridge_one_shot/inspect_blocked_issue43.py')
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise RuntimeError('redirect denied')
try:
    with urllib.request.build_opener(NoRedirect).open(url, timeout=20) as response:
        data = response.read(65537)
    if not data or len(data) > 65536 or hashlib.sha256(data).hexdigest() != '505e0db2165499a26925348925523e53c7284346c8f87b608cc1344d8ce2b50b':
        raise RuntimeError('immutable source digest mismatch')
    folder = pathlib.Path(tempfile.mkdtemp(prefix='signal-desk-issue43-inspect-', dir='/root'))
    path = folder / 'inspect_blocked_issue43.py'
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    result = subprocess.run(['python3', '-I', '-B', str(path),
        '--workspace', workspace, '--report'], check=False)
    if result.returncode:
        raise SystemExit('STOP: DIAGNOSTIC_PRESERVE_STATE; no retry or cleanup')
except Exception:
    raise SystemExit('STOP: DIAGNOSTIC_ENTRY_PRESERVE_STATE') from None
PY
)
```

Expected: `GITHUB_DIAGNOSTIC_REPORT: <comment-id>` and
`HOST_RUNTIME: PRESERVED; no Docker, Git, cleanup, model or task action`.
Manager reads the sanitized report directly on GitHub; Ali need not relay logs
or report text. If STOP occurs, preserve all files/resources and do not repeat
or remove the reporting marker. No retry, cleanup or scheduler follows from
successful diagnosis; those need an exact reviewed reconciliation decision.

#45 remains dormant, the installed hourly loop is unverified, and #44 portable
single-container installation/secured restore is the subsequent deliverable.
