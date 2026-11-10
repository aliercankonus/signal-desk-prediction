# Finish only the verified incomplete preparation clone

The operator's #65 probe reports a source candidate commit, a runner .git-only
tree with a different HEAD/ref set, a missing runner candidate, no FETCH_HEAD,
an existing prefix-completion intent and no final receipt. These categories do
not prove that the runner is an untouched clone; arbitrary OTHER_COMMIT state
must be preserved. The reviewed entry below proves clone correspondence before
any correction. No blind fetch, checkout, reset or old-entry repetition.

The exact original #62 spec/cursors/v2 source and protected cold receipts/public
verifier must match. V4 requires the same root-owned source/runner, exact source
and runner symbolic HEAD, resolved HEAD commit, and a complete normal-clone ref
mapping: source heads map to origin remote heads, the sole local default branch
and origin/HEAD match, and tags are identical. Unexpected or changed refs fail;
no ref or branch is reset/deleted. Runner must have only .git, no index, locks,
ORIG_HEAD, shallow/alternate/shared store or active hooks. Closed Git-config key
admission rejects includes, credential keys, URL rewrites, aliases, fsmonitor and
other custom execution/transport behavior. Raw values/refs are never printed.

Every other staged phase is checked: exact frozen public bundle bytes/manifest,
empty auth/context/home/inbox/journals/queue/claim directory, the specific prior
root-0600 completion intent, and absent policy/plan/handoff/final/new intent.
Nonempty claims/history or an already present candidate stops. This is completion
of the proven inert preparation clone, not continuation of a blocked real task.
Historical runs, credentials, old host runner and original spec/start stay intact.

After source/mount/image/static Compose checks and a fresh checkpoint check, the
explicit operator --complete action exclusively fsyncs a new Git-completion
intent. It fetches ONLY the frozen candidate SHA from the protected local source
path, with no refspec, tags, FETCH_HEAD writes, submodules, auto maintenance or
network transport. HTTP/SSH/ext are disabled; only local file transport is allowed;
credential helpers, hooks, lazy fetch, replacements and ambient Git config are
disabled. Source refs/HEAD/FETCH_HEAD and runner refs/HEAD/FETCH_HEAD are compared
before/after transfer. It then performs the originally intended normal detached
checkout (no force/reset/clean), preserving all existing branch/tag refs. Root
Git operations, source/ref checks and final cleanliness finish before the worker
ownership transfer; no root Git command follows transfer. Remaining inert files
and the final receipt are published exclusively. Keys/tokens remain unread and
uninstalled; only the public verifier is read.

Default invocation is read-only preview. Runtime, provider/device login, signer,
network/service/container, :30 scheduler activation and real dispatch remain
NO-GO. Presence of policy/context files is never task authority. A changed or
ambiguous checkpoint stops rather than relaxing checks or making another attempt.

## One operator block

Manager fills the immutable commit/helper SHA256 and known private workspace.
The helper downloads only individually hash-pinned public dependencies from the
same commit; v4's public-source cap is 65536 bytes, not an unbounded file read.
Ali does not supply JSON, locate paths or relay reports through Hermes.

```bash
env -i PATH=/usr/bin:/bin HOME=/root LC_ALL=C \
  SD_FINISH_COMMIT='MANAGER_REVIEWED_COMMIT' \
  SD_FINISH_SHA256='MANAGER_REVIEWED_SHA256' \
  SD_FINISH_WORKSPACE='MANAGER_SUPPLIED_PRIVATE_WORKSPACE' \
  /usr/bin/python3 -I -B - <<'PY'
import hashlib, os, re, signal, sys, urllib.request
commit,digest=os.environ['SD_FINISH_COMMIT'],os.environ['SD_FINISH_SHA256']
if os.geteuid()!=0 or not re.fullmatch('[0-9a-f]{40}',commit) or not re.fullmatch('[0-9a-f]{64}',digest):
    raise SystemExit('STOP: INVALID_FINISH_PIN')
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('redirect')
def timeout(*args):raise TimeoutError()
previous=signal.signal(signal.SIGALRM,timeout);signal.alarm(20)
try:
    url=('https://raw.githubusercontent.com/aliercankonus/signal-desk-prediction/'+
         commit+'/ops/bridge_one_shot/finish_cloned_staging.py')
    with urllib.request.build_opener(NoRedirect).open(url,timeout=15) as response:
        source=response.read(32769)
    if len(source)>32768 or hashlib.sha256(source).hexdigest()!=digest:raise ValueError('digest')
except Exception:
    raise SystemExit('STOP: PUBLIC_FINISH_SOURCE; completion not called')
finally:
    signal.alarm(0);signal.signal(signal.SIGALRM,previous)
sys.argv=['reviewed-finish','--workspace',os.environ['SD_FINISH_WORKSPACE'],
          '--source-commit',commit,'--complete']
exec(compile(source,'<reviewed-finish>','exec'),{'__name__':'__main__'})
PY
```

Expected CLONED_STAGING COMPLETE_NO_ACTIVATION; ORIGINAL_SPEC_BOOTSTRAP PRESERVED;
WORKER_CREDENTIALS NOT_INSTALLED; PROVIDER_AUTH NOT_STARTED; overall NO-GO.
Return only fixed status/error lines. New STOP/timeout/interruption means preserve
all objects/files/intents; no retry, deletion, ownership change or alternate
attempt. Fixed errors show only category/reviewed-code site, never exception
values. This automation does not run host operations. #44 portable single-container
build and separately secured backup/restore remain subsequent to #41 completion.
