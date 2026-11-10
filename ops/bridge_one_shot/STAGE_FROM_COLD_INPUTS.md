# Derive and stage from the accepted cold-input receipt

This is the next #41 operator boundary after COLD_READY. Do not run the old
19-prompt guide, reconstruct JSON, repeat token creation, install a service or
ask Ali to relay work through Hermes. The manager supplies one completely filled
immutable loader. Automation never runs it on the VPS.

Default `stage_from_cold_inputs.py` is preview-only. Explicit `--stage` creates
one fixed fresh attempt's root-only spec, reviewed bootstrap v2 source and receipt,
plus the existing bootstrap's fresh runner/bundle/context/home/state/inbox files.
It uses source and venv paths already recorded privately; requires matching
protected setup/intent/cold receipts and current private-file metadata; reads only
the public verifier bytes; derives the existing frozen consumer's full schema.
No private key or either token's contents is read, copied, replaced or installed.
The old worker-owned runner and venv are not changed. Existing destination or
signer claim state stops rather than being recovered, cleaned or retried.

Bootstrap v2 is separately versioned. Its only delta from the #50 frozen
bootstrap is the image environment inspection: obtain names in Docker's formatter,
ignore one terminal empty record and retain sensitive/invalid/count guards.
Full Config.Env values are never requested. All runner ownership ordering, fresh
clone/cleanliness, bound Compose render and source checks remain the same.
Historical runner 00acd27132b68264ee2ab1692d3024f09c640c6d is preserved; the
separately reviewed candidate stays e84021a786004456a12de9e25eae50d191da6cf1,
adapter eac843de7967d48cce56ee9a198750e98754a2de. The original guide/consumer
hash gates remain unchanged; v2 is used only for the final staging call.

The declared Python 3.14.9/pytest 8.3.3 context comes from historical reviewed
configuration, not a fresh runtime execution. Venv admission is metadata-only.
The supplied comment cursors are manager-selected historical boundaries, never
task authority. The staged policy is dormant and cannot grant any operation by
itself. Manager/App exclusivity, host/image internal isolation, actual worker
credentials, provider authentication, installed watcher and first loop remain
UNPROVEN. No container/network/service is started, no signature/grant is posted,
no provider/model request or real task dispatch is made. Worker token stays cold.
The :30 Europe/Amsterdam persistent scheduler is not installed by this entry.

## One operator block

The manager privately fills the values and supplies the whole block. The entry
and both public dependencies are fetched only from the same immutable repository
commit, with individual known SHA256 gates before compilation and finite limits.
Dependencies are public source only, never downloaded host configuration or code
from arbitrary URLs. No file execution occurs on a source digest mismatch.

```bash
env -i PATH=/usr/bin:/bin HOME=/root LC_ALL=C \
  SD_STAGE_COMMIT='MANAGER_REVIEWED_COMMIT' \
  SD_STAGE_SHA256='MANAGER_REVIEWED_SHA256' \
  SD_STAGE_WORKSPACE='MANAGER_SUPPLIED_PRIVATE_WORKSPACE' \
  SD_CURSOR41='MANAGER_SELECTED_CURSOR' SD_CURSOR45='MANAGER_SELECTED_CURSOR' \
  /usr/bin/python3 -I -B - <<'PY'
import hashlib, os, re, signal, sys, urllib.request
commit, digest = os.environ['SD_STAGE_COMMIT'], os.environ['SD_STAGE_SHA256']
workspace = os.environ['SD_STAGE_WORKSPACE']
if (os.geteuid() != 0 or not re.fullmatch('[0-9a-f]{40}', commit) or
        not re.fullmatch('[0-9a-f]{64}', digest) or not workspace.startswith('/') or
        not all(re.fullmatch('[0-9]{1,20}', os.environ[k]) for k in ('SD_CURSOR41','SD_CURSOR45'))):
    raise SystemExit('STOP: INVALID_REVIEWED_STAGE_INPUTS')
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): raise ValueError('redirect')
def timeout(*args): raise TimeoutError()
previous = signal.signal(signal.SIGALRM, timeout)
signal.alarm(20)
try:
    url = ('https://raw.githubusercontent.com/aliercankonus/signal-desk-prediction/' +
           commit + '/ops/bridge_one_shot/stage_from_cold_inputs.py')
    with urllib.request.build_opener(NoRedirect).open(url, timeout=15) as response:
        source = response.read(32769)
    if len(source) > 32768 or hashlib.sha256(source).hexdigest() != digest:
        raise ValueError('digest')
except Exception:
    raise SystemExit('STOP: PUBLIC_STAGE_SOURCE; no staging entry called')
finally:
    signal.alarm(0)
    signal.signal(signal.SIGALRM, previous)
sys.argv = ['reviewed-stage', '--workspace', workspace, '--source-commit', commit,
            '--cursor41', os.environ['SD_CURSOR41'], '--cursor45', os.environ['SD_CURSOR45'], '--stage']
exec(compile(source, '<reviewed-stage>', 'exec'), {'__name__':'__main__'})
PY
```

Expected: DERIVED_SPEC WRITTEN_ROOT_ONLY; STAGING COMPLETE_NO_ACTIVATION;
WORKER_CREDENTIALS NOT_INSTALLED; PROVIDER_AUTH NOT_STARTED; OVERALL NO-GO.
Return only these fixed lines or STOP. No paths, JSON, private keys, tokens or raw
logs. A spec/source/partial staging directory may remain after a failed attempt:
preserve it and stop for read-only manager reconciliation. Never rerun, remove,
chown, overwrite or widen source/runtime authority to get past a refusal.

The fixed attempt's staged signer start/budget is not a promise of later
activation. A delayed first-loop request must be reviewed against its actual
receipts and authorization windows; never rewrite an existing policy or reuse a
historical claim. Provider device login, worker token enrollment and first runtime
remain separate explicit operator actions with reviewed entries. #44 true portable
single-container build and separately secured backup/restore follows #41 completion.
