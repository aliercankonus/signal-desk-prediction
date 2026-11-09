# Operator step: prepare the private setup workspace

Prerequisite: the operator has reported the PR #58 source-object preparation
successful. Do not repeat that fetch or rebuild/change ownership of the historical
runner. This step resolves the previously unconfigured setup parent and installs
the existing reviewed public guide/installer for manager-controlled reuse.

The manager supplies the immutable entry commit/SHA256 and the three private
paths in one complete handoff; Ali does not locate files, write JSON or answer
the guide's 19 prompts. The target setup directory must be fresh. The entry reads
only pinned public Git blobs, bounded current Docker mount metadata (at most 32
containers, 64 mounts each), and optional venv ownership/mode metadata. It checks
both bind and volume source ancestry before publication. It never reads Docker
environment values, private keys, auth stores or credential contents, and never
executes a worker-owned interpreter or modifies an existing venv.

`prepare_setup_workspace.py --source <private-store> --parent <fresh-parent>` is
preview-only. The exact manager-supplied root invocation below uses `--apply`:
it exclusively creates one root-owned 0700 directory, two hash-verified public
helper files and a root-private metadata manifest, all 0600, with fsync. Existing
names, untrusted ancestry, overlapping/malformed mount metadata or digest failure
stop before publication. A failure during publication preserves partial state;
never overwrite, retry or clean it automatically.

This is public preparation, not a private spec or enrollment. Do not run the
installed guide/installer manually or treat the manifest as task authority. It
contains actual supplied paths and metadata, not fabricated credential files.
Private keys, tokens, worker credentials, provider login, network/service changes
and dispatch are **not** performed. Current mount metadata is not proof of image,
credential or manager-App isolation. Enrollment/runtime gates remain UNPROVEN.

The bounded loader below verifies the reviewed source before execution, keeps
it in memory and installs no loader. Missing/invalid fields stop before download.
The manager fills the fields privately; values must never be committed or echoed
in GitHub. Do not run placeholders or a mutable branch URL.

```bash
(
set +x
/usr/bin/env -i PATH=/usr/bin:/bin HOME=/nonexistent LC_ALL=C \
SD_SETUP_ENTRY_COMMIT="${SD_SETUP_ENTRY_COMMIT-}" \
SD_SETUP_ENTRY_SHA256="${SD_SETUP_ENTRY_SHA256-}" \
SD_SETUP_SOURCE="${SD_SETUP_SOURCE-}" \
SD_SETUP_PARENT="${SD_SETUP_PARENT-}" \
SD_SETUP_VENV="${SD_SETUP_VENV-}" \
/usr/bin/python3 -I -B - <<'PY'
import hashlib, os, re, signal, sys, urllib.request

commit = os.environ.get('SD_SETUP_ENTRY_COMMIT', '')
digest = os.environ.get('SD_SETUP_ENTRY_SHA256', '')
source_store = os.environ.get('SD_SETUP_SOURCE', '')
parent = os.environ.get('SD_SETUP_PARENT', '')
venv = os.environ.get('SD_SETUP_VENV', '')
if (os.geteuid() != 0 or not re.fullmatch('[0-9a-f]{40}', commit) or
        not re.fullmatch('[0-9a-f]{64}', digest) or
        not source_store.startswith('/') or not parent.startswith('/')):
    raise SystemExit('STOP: reviewed root handoff fields required; no changes made')
url = ('https://raw.githubusercontent.com/aliercankonus/signal-desk-prediction/'
       + commit + '/ops/bridge_one_shot/prepare_setup_workspace.py')
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
sys.argv = ['prepare_setup_workspace.py', '--source', source_store,
            '--parent', parent, '--venv', venv, '--apply']
exec(compile(source, '<reviewed-setup-entry>', 'exec'), {'__name__': '__main__'})
PY
)
```

Expected: SETUP_WORKSPACE PREPARED; GUIDE_INSTALLER HASH_VERIFIED;
VENV_PRIVATE_SOURCE (READY_METADATA_ONLY, PRIVATE_COPY_REVIEW_REQUIRED or UNPROVEN);
SECRETS_AUTH_SERVICES NOT_CREATED; overall NO-GO. None of the venv statuses is
execution proof or an instruction to chmod the existing source. Return these fixed
summary lines to the manager, not private paths, mount lists or the manifest.
STOP/timeout/partial state => preserve files and report the fixed status only.
The manager prepares the remaining private enrollment steps from this result.
