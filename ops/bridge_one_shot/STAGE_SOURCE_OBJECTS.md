# Operator step: add reviewed public Git objects only

This addresses the reported protected bare store with unavailable reviewed pins.
It does not repair or recreate a runner. The historical worker-owned runner,
its pin, credentials, services, data and blocked runs remain untouched.

The manager supplies the exact entry commit, SHA256 and private store path in a
single private copyable handoff. Ali does not construct JSON or locate signer
files. Never publish private paths or identities in GitHub. Do not run placeholders,
an unreviewed head or a changing branch URL. The block below stops before fetching
when the required manager-supplied fields are absent/invalid.

`stage_source_objects.py --store <private-store>` is preview-only. An explicitly
reviewed operator invocation with `--apply`, including the entry below, adds
public objects for fixed source `d21e19d7be85f9bf402e42b6f130846e022eb5e4`.
It disables credential helpers, hooks and automatic maintenance, uses only the
fixed public HTTPS repository, refuses shallow/partial or auth/include/rewrite
configuration rather than altering it, and verifies commit types/ancestry.
There is no branch/tag destination refspec. Existing refs, HEAD and FETCH_HEAD are
checked unchanged; failures preserve state without retry, cleanup, reset or repair.
Only intended Git object-transfer writes occur. No keys, credentials, configs,
worker homes, services, network rules, enrollment, model calls or dispatch are made.

The immutable-entry loader below downloads at most 32768 bytes into memory,
with a 20-second fetch deadline, verifies the manager-supplied SHA256 before
executing it, and never installs a helper file. It requires Python 3 and public
HTTPS access. It does not read credentials. The three `SD_SOURCE_*` fields are
private handoff data, not authority or host GO. Only the operator's specifically
reviewed invocation authorizes this source-only preparation.

```bash
(
set +x
/usr/bin/env -i PATH=/usr/bin:/bin HOME=/nonexistent LC_ALL=C \
SD_SOURCE_ENTRY_COMMIT="${SD_SOURCE_ENTRY_COMMIT-}" \
SD_SOURCE_ENTRY_SHA256="${SD_SOURCE_ENTRY_SHA256-}" \
SD_SOURCE_STORE="${SD_SOURCE_STORE-}" \
/usr/bin/python3 -I -B - <<'PY'
import hashlib, os, re, signal, sys, urllib.request

commit = os.environ.get('SD_SOURCE_ENTRY_COMMIT', '')
digest = os.environ.get('SD_SOURCE_ENTRY_SHA256', '')
store = os.environ.get('SD_SOURCE_STORE', '')
if (os.geteuid() != 0 or not re.fullmatch('[0-9a-f]{40}', commit) or
        not re.fullmatch('[0-9a-f]{64}', digest) or not store.startswith('/')):
    raise SystemExit('STOP: reviewed root handoff fields required; no changes made')
url = ('https://raw.githubusercontent.com/aliercankonus/signal-desk-prediction/'
       + commit + '/ops/bridge_one_shot/stage_source_objects.py')
def deadline(*_):
    raise TimeoutError()
signal.signal(signal.SIGALRM, deadline)
signal.alarm(20)
try:
    with urllib.request.urlopen(url, timeout=10) as response:
        source = response.read(32769)
    if len(source) > 32768 or hashlib.sha256(source).hexdigest() != digest:
        raise ValueError()
except Exception:
    raise SystemExit('STOP: source unavailable or digest mismatch; no changes made')
finally:
    signal.alarm(0)
sys.argv = ['stage_source_objects.py', '--store', store, '--apply']
exec(compile(source, '<reviewed-source-entry>', 'exec'), {'__name__': '__main__'})
PY
)
```

Expected success: `SOURCE_OBJECTS: VERIFIED`, `REFS_HEAD_FETCH_HEAD: UNCHANGED`,
`RUNNER_CREDENTIALS_SERVICES: UNTOUCHED`, then **OVERALL: NO-GO**. This closes
the source-object preparation gate only. Timeout, configuration refusal, changed
refs or failed pin check => STOP, preserve state, send only the sanitized fixed
status lines to the manager; no automatic retry or workaround. A fetch may have
added some public objects before failing, so failure is not proof of no writes.

The manager reviews the result and the next consolidated enrollment handoff.
No installation, host isolation, credentials, persistent watcher or first real
Bridge loop is established by this source preparation.
