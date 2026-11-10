# One operator authentication boundary, without a task

V2 preparation is complete only when its operator receipt says so. That does not
authorize host execution. The manager must first obtain explicit user approval for
this concrete boundary: temporary proxy/worker containers, two attempt-owned bridge
networks, scoped worker firewall rules, authenticated read-only GitHub requests,
and one interactive provider device login. The automation must never execute this
on the VPS. No real task, model inference, signing, inbox enrollment/enable,
scheduler, grant/report POST or service installation is part of this entry.

`authenticate_worker_once.py` reuses the exact #69 v2 bundle. Default/review mode
validates protected files and metadata only. It never opens root signer keys or
root/worker credential values. Explicit `--authenticate` requires a live operator
TTY and allocates one non-resumable root-private journal before runtime effects.
Root source/bundle/spec/plan and the original authority/cursors/pins remain intact.

Before effects it refuses existing attempt resources/chains/subnet collisions,
direct exposure of protected root paths to existing bind mounts, or observed broad
host escape configuration on an existing instance of the same Hermes image. It
does not certify all existing host infrastructure or arbitrary baked image contents;
the pinned image and host remain operator trust prerequisites. These checks do not
establish manager-exclusive GitHub App invocation.

The controller renders the verified v2 Compose source into an exclusive root-private
auth-only configuration. Runner, state, auth, context, inbox and the selected public
helpers are read-only; only the dedicated worker home is persistent and writable.
Fresh tmpfs masks `/root`, `/home` and `/opt/data` except the exact read-only venv
submount. Actual container image/labels/user, namespaces, capability/device absence,
resource limits, no-new-privileges, root filesystem, bind sources/permissions,
environment **names only**, networks, peers and lack of published ports are checked
before credential use. No Docker socket or broad host directory is mounted.

The worker first runs its owner/config gate, then the existing authenticated
read-only GitHub probe. If either fails, provider login is never started. Next the
installed `hermes auth add --help` must support `--type`, `--no-browser` and `--timeout`.
Only then does the operator TTY run:

```text
hermes auth add openai-codex --type oauth --no-browser --timeout 480
```

This command runs inside the verified exact worker, not in the old Hermes container
or root home. The operator personally opens the displayed provider URL and approves
the device code. Do not paste the device code, browser output, auth store, account
details or any token into GitHub/chat. Only the final fixed summary is shareable.
The controller never captures provider TTY output in a journal. The device command
has a whole-process 480-second cap inside an overall 1200-second budget, including
420 seconds reserved for cleanup. A timed-out Docker client is killed and the exact
container is stopped/removed during cleanup; terminal attributes are restored.

On the identified path, only the recorded worker/proxy IDs, exact dedicated firewall
jumps/chains and empty labeled networks are removed. Private homes/auth stores,
journals, source, runner and historical runs are retained. Partial startup, unknown
identity, timeout/interruption or failed cleanup preserves the intent/resources and
never triggers a retry, prune, force remove, another login or an invented success.
If other host resources change, baseline readback also refuses verified cleanup.

Expected fixed summary: `GITHUB_READONLY: VERIFIED_WORKER_NAMESPACE`,
`PROVIDER_DEVICE_LOGIN: CLI_REPORTED_SUCCESS`, `AUTH_RUNTIME_CLEANUP: EXACT_IDS_VERIFIED`,
and `SIGNING_ENROLLMENT_TIMER_DISPATCH: NOT_STARTED`. Overall remains NO-GO: CLI login
does not prove model entitlement, manager/App exclusivity, real task authority,
an installed hourly watcher, or the first end-to-end loop. Those require subsequent
explicit authority and reviewed evidence. #45 remains dormant; #44 is subsequent.

## Source references and installed-version limit

Official Hermes references describe device code as the default Codex flow and a
separate Hermes auth store. The currently installed CLI is not inferred from those
current documents; its help is checked locally by the operator entry before login.
The dedicated config disables external-login adoption; old homes are masked.

- https://hermes-agent.nousresearch.com/docs/integrations/providers
- https://github.com/NousResearch/hermes-agent/blob/main/hermes_cli/subcommands/auth.py
- https://github.com/NousResearch/hermes-agent/blob/main/hermes_cli/auth_codex.py

## Reviewed execution proposal — requires user approval first

The manager supplies the existing private workspace; no new spec/token or path
search. Do not execute this proposal without the user's explicit host/runtime and
provider authentication approval. The loader verifies immutable public bytes,
then reconnects stdin to the operator TTY (a here-document is not an interactive
TTY). Device URL/code remain visible only in that terminal.

```bash
python3 -I -B - "$EXISTING_PRIVATE_WORKSPACE" <<'PYCODE'
import hashlib, os, signal, sys, urllib.request
source = '73ed6f658bab7d766d2db2f80d6a7bf431997516'
digest = '98e90c15d5b20bf4fcf0739b830f1bd60b38ca0405d3adfdee20bcca4b40f378'
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): raise RuntimeError('redirect refused')
def expired(*_): raise TimeoutError()
signal.signal(signal.SIGALRM, expired)
signal.alarm(20)
try:
    url = 'https://raw.githubusercontent.com/aliercankonus/signal-desk-prediction/'+source+'/ops/bridge_one_shot/authenticate_worker_once.py'
    with urllib.request.build_opener(NoRedirect).open(url, timeout=15) as response:
        data = response.read(65537)
    if len(data)>65536 or hashlib.sha256(data).hexdigest()!=digest:
        raise RuntimeError('digest mismatch')
except Exception:
    print('STOP: AUTH_ONLY_SOURCE_UNVERIFIED; preserve state; no retry')
    raise SystemExit(1)
finally:
    signal.alarm(0)
namespace = {'__name__':'reviewed_auth_only'}
exec(compile(data, '<reviewed-auth-only>', 'exec'), namespace)
sys.argv = ['auth-only', '--workspace', sys.argv[1], '--authenticate']
try:
    tty = os.open('/dev/tty', os.O_RDWR)
    os.dup2(tty, 0)
    sys.stdin = os.fdopen(os.dup(tty), 'r', buffering=1)
    os.close(tty)
except OSError:
    print('STOP: LIVE_OPERATOR_TTY_REQUIRED; no runtime started')
    raise SystemExit(1)
raise SystemExit(namespace['main']())
PYCODE
```

