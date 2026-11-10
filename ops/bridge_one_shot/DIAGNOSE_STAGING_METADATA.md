# Read-only diagnosis after the #62 generic staging refusal

Do not rerun staging, delete partial files, change ownership or invent a new
attempt. The manager cannot identify the failing phase from STAGING_UNVERIFIED
alone. `diagnose_staging_metadata.py --workspace <manager-supplied-private-path>`
is a read-only operator entry for this specific fixed attempt.

It opens only the existing protected nonsecret setup manifest (root owner,
private mode, regular file, no symlink, maximum 8192 bytes). It prints only known
venv status plus bounded integer UID/GID/mode fields. Existing venv/config paths
and fixed signer-claim/attempt paths are lstat-only: existence/type/UID/GID/mode,
no contents, no symlink targets and no private path strings. It never opens an
attempt spec, private key, token or auth store. It never invokes Git, Docker,
a worker interpreter, network tools, staging, signing, a service or a task.
No files are created, changed or removed.

The manager supplies a complete loader with the reviewed immutable source SHA
and helper SHA256, verified before compilation, plus the already known private
workspace. The following loader is the exact supported procedure; no manual file
editing is necessary.

```bash
env -i PATH=/usr/bin:/bin HOME=/root LC_ALL=C \
  SD_DIAG_COMMIT='MANAGER_REVIEWED_COMMIT' \
  SD_DIAG_SHA256='MANAGER_REVIEWED_SHA256' \
  SD_DIAG_WORKSPACE='MANAGER_SUPPLIED_PRIVATE_WORKSPACE' \
  /usr/bin/python3 -I -B - <<'PY'
import hashlib, os, re, signal, sys, urllib.request
commit, digest = os.environ['SD_DIAG_COMMIT'], os.environ['SD_DIAG_SHA256']
if os.geteuid() != 0 or not re.fullmatch('[0-9a-f]{40}', commit) or not re.fullmatch('[0-9a-f]{64}', digest):
    raise SystemExit('STOP: INVALID_DIAGNOSTIC_PIN')
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): raise ValueError('redirect')
def timeout(*args): raise TimeoutError()
previous = signal.signal(signal.SIGALRM, timeout)
signal.alarm(20)
try:
    url = ('https://raw.githubusercontent.com/aliercankonus/signal-desk-prediction/' +
           commit + '/ops/bridge_one_shot/diagnose_staging_metadata.py')
    with urllib.request.build_opener(NoRedirect).open(url, timeout=15) as response:
        source = response.read(16385)
    if len(source) > 16384 or hashlib.sha256(source).hexdigest() != digest:
        raise ValueError('digest')
except Exception:
    raise SystemExit('STOP: PUBLIC_DIAGNOSTIC_SOURCE; no diagnostic called')
finally:
    signal.alarm(0)
    signal.signal(signal.SIGALRM, previous)
sys.argv = ['reviewed-metadata', '--workspace', os.environ['SD_DIAG_WORKSPACE']]
exec(compile(source, '<reviewed-metadata>', 'exec'), {'__name__':'__main__'})
PY
```

Return only its fixed metadata lines and READ_ONLY_COMPLETE, or STOP. Existing
files/directories remain preserved. Presence is not proof of successful staging
or authority. In particular READY_METADATA_ONLY does not itself establish GID
10000, runtime capability or manager-exclusive invocation. The manager uses the
observed phase/metadata to bound the correction; no blind retry, cleanup,
credential re-provisioning or host/runtime activation is permitted.
