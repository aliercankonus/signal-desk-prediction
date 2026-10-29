#!/usr/bin/env bash
# REVIEW ONLY. Run manually in a trusted root terminal after independent approval.
# Existing recovery evidence only; never invoke collection, audit, replay or deployment.
# The invoking root shell must itself be trusted: Bash startup (BASH_ENV) runs
# before the first script statement, so no in-script unset can undo that stage.
set -Eeuo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
unset BASH_ENV ENV PYTHONPATH PYTHONHOME PYTHONOPTIMIZE PYTHONSTARTUP PYTHONINSPECT PYTHONUSERBASE CDPATH GLOBIGNORE
umask 077
PIN=5696c6cd17c4dc808c7fd3e42c47fc131f3873f3
SID=cb8a0767d7284b8aaa3d09fbca7095f2
for key in RESEARCH_RECOVERY_EVIDENCE RESEARCH_ORIGINAL_EVIDENCE RESEARCH_WORK_PARENT \
  RESEARCH_CHECKOUT_PARENT RESEARCH_REMOTE RESEARCH_IMAGE_REPO \
  RESEARCH_ACTIVE_SETTINGS RESEARCH_CANDIDATE_SETTINGS RESEARCH_GUARD \
  RESEARCH_EXPECTED_HOST RESEARCH_AGENT_NAME_FILTER RESEARCH_PRIOR_EVIDENCE \
  RESEARCH_CONFIG_DIR RESEARCH_EXPECTED_ACTIVE_HEAD RESEARCH_APPROVAL_SHA256 \
  RESEARCH_SOURCE_IDLE_CONFIRMED RESEARCH_BASE_IMAGE_ID; do
  [[ -n ${!key:-} ]] || { printf 'Missing operator-reviewed parameter: %s\n' "$key" >&2; exit 2; }
done
[[ $(id -u) == 0 ]] || { echo 'Trusted root terminal required' >&2; exit 2; }
[[ $RESEARCH_IMAGE_REPO =~ ^[a-z0-9][a-z0-9._/-]*$ &&
   $RESEARCH_EXPECTED_HOST =~ ^[A-Za-z0-9._-]+$ &&
   $RESEARCH_AGENT_NAME_FILTER =~ ^[A-Za-z0-9_.-]+$ &&
   $RESEARCH_EXPECTED_ACTIVE_HEAD =~ ^[0-9a-f]{40}$ &&
   $RESEARCH_APPROVAL_SHA256 =~ ^[0-9a-f]{64}$ &&
   $RESEARCH_BASE_IMAGE_ID =~ ^sha256:[0-9a-f]{64}$ &&
   $RESEARCH_SOURCE_IDLE_CONFIRMED == operator-verified-exclusive-writer-control-and-source-idle &&
   $RESEARCH_REMOTE != -* ]] || { echo 'Invalid operator parameter/idle attestation' >&2; exit 2; }
SCRIPT=$(realpath -e -- "${BASH_SOURCE[0]}")
HELPER=${SCRIPT%/*}/research_copy_gates.py
OUTPUT_GATES=${SCRIPT%/*}/research_output_gates.py
RECOVERY_GATES=${SCRIPT%/*}/soak_recovery_gates.py
SOAK_GATES=${SCRIPT%/*}/soak_gates.py
BASE_GATES=${SCRIPT%/*}/acceptance_gates.py
for path in "$SCRIPT" "$HELPER" "$OUTPUT_GATES" "$RECOVERY_GATES" "$SOAK_GATES" "$BASE_GATES" "$RESEARCH_RECOVERY_EVIDENCE" "$RESEARCH_ORIGINAL_EVIDENCE" \
  "$RESEARCH_WORK_PARENT" "$RESEARCH_CHECKOUT_PARENT" "$RESEARCH_ACTIVE_SETTINGS" \
  "$RESEARCH_CANDIDATE_SETTINGS" "$RESEARCH_GUARD" "$RESEARCH_PRIOR_EVIDENCE" \
  "$RESEARCH_CONFIG_DIR"; do
  [[ $path == /* && ! -L $path ]] || { echo 'Absolute, nonsymlink paths required' >&2; exit 2; }
done
[[ $(hostname) == "$RESEARCH_EXPECTED_HOST" ]] || { echo 'Host mismatch' >&2; exit 2; }
# Refuse an agent-writable or agent-mounted copy of this procedure or its helper.
# All output parents must be private, protected, disjoint and outside agent mounts.
python3 - "$SCRIPT" "$HELPER" "$OUTPUT_GATES" "$RECOVERY_GATES" "$SOAK_GATES" "$BASE_GATES" "$RESEARCH_RECOVERY_EVIDENCE" "$RESEARCH_ORIGINAL_EVIDENCE" \
  "$RESEARCH_WORK_PARENT" "$RESEARCH_CHECKOUT_PARENT" "$RESEARCH_ACTIVE_SETTINGS" \
  "$RESEARCH_CANDIDATE_SETTINGS" "$RESEARCH_GUARD" "$RESEARCH_PRIOR_EVIDENCE" \
  "$RESEARCH_CONFIG_DIR" "$RESEARCH_AGENT_NAME_FILTER" <<'PY'
import json, pathlib, stat, subprocess, sys
paths = [pathlib.Path(x) for x in sys.argv[1:-1]]
script, helper, output_gates, recovery_gates, soak_gates, base_gates, recovery, original, work, checkout, active, candidate, guard, prior, config = paths
name_filter = sys.argv[-1]
def protected_path(path):
    assert str(path) == str(path.resolve(strict=True)), 'Linked/noncanonical path'
    for part in (path, *path.parents):
        st = part.lstat()
        assert st.st_uid == 0 and not stat.S_ISLNK(st.st_mode) and not st.st_mode & 0o022, 'Unprotected ancestor'
for path in paths:
    protected_path(path)
for path in (script, helper, output_gates, recovery_gates, soak_gates, base_gates, active, candidate, guard):
    assert path.is_file(), 'Required regular protected file missing'
for path in (recovery, original, work, checkout, prior, config):
    assert path.is_dir(), 'Required protected directory missing'
for path in (recovery, original, work, checkout, prior, config):
    assert not path.stat().st_mode & 0o077, 'Private evidence/config/checkout parent required'
settings = json.loads(active.read_text())
agent = settings['agent_container_id']
assert isinstance(agent, str) and len(agent) == 64 and all(c in '0123456789abcdef' for c in agent)
ids = [agent] + subprocess.check_output(['docker','ps','-aq','--filter',f'name={name_filter}'],text=True,timeout=15).splitlines()
sources = []
for cid in set(ids):
    item = json.loads(subprocess.check_output(['docker','inspect',cid],text=True,timeout=15))[0]
    sources += [pathlib.Path(m['Source']).resolve() for m in item['Mounts']]
def overlaps(a, b):
    return a == b or a.is_relative_to(b) or b.is_relative_to(a)
def outside_agent_mount(path):
    assert not any(overlaps(path, mount) for mount in sources), 'Path overlaps agent mount'
for path in paths:
    outside_agent_mount(path)
for parent in (work, checkout):
    for other in (script.parent, recovery, original, active, candidate, guard, prior, config):
        assert not overlaps(parent, other), 'Output overlaps protected input'
assert not overlaps(work, checkout), 'Output parents overlap'
PY
[[ $(stat -c %s "$RECOVERY_GATES") -le 1048576 &&
   $(stat -c %s "$SOAK_GATES") -le 1048576 &&
   $(stat -c %s "$BASE_GATES") -le 1048576 &&
   $(sha256sum "$RECOVERY_GATES" | cut -d' ' -f1) == 4728798c9c8668375f793db906fe9277ad4bb409f9ddb99f2b3c8d477326a27f &&
   $(sha256sum "$SOAK_GATES" | cut -d' ' -f1) == ad19e237bc6c816a1a218cf269fdfce06248c693a95437016bedba2ef34a09a4 &&
   $(sha256sum "$BASE_GATES" | cut -d' ' -f1) == 575571200739f6d3aeacb22aba7faa09e3b855449872cb7484ca891f49fe6a48 ]] || {
  echo 'Staged recovery dependency differs from pinned merged commit' >&2; exit 2;
}
[[ $(stat -c %s "$RESEARCH_PRIOR_EVIDENCE/active-head.txt") -le 128 &&
   $(<"$RESEARCH_PRIOR_EVIDENCE/active-head.txt") == "$RESEARCH_EXPECTED_ACTIVE_HEAD" &&
   $(stat -c %s "$RESEARCH_CANDIDATE_SETTINGS") -le 4194304 &&
   $(sha256sum "$RESEARCH_CANDIDATE_SETTINGS" | cut -d' ' -f1) == "$RESEARCH_APPROVAL_SHA256" ]]
mapfile -t active_fields < <(timeout 180s python3 "$RESEARCH_GUARD" verify --settings "$RESEARCH_ACTIVE_SETTINGS")
mapfile -t candidate_fields < <(timeout 180s python3 "$RESEARCH_GUARD" verify --settings "$RESEARCH_CANDIDATE_SETTINGS")
[[ ${#active_fields[@]} == 3 && ${#candidate_fields[@]} == 3 ]] || exit 2
ACTIVE=${active_fields[0]}; PROJECT=${active_fields[1]}; HOST=${active_fields[2]}
RELEASE=${candidate_fields[0]}
[[ $HOST == "$RESEARCH_EXPECTED_HOST" && ${candidate_fields[1]} == "$PROJECT" &&
   ${candidate_fields[2]} == "$HOST" && $RELEASE != "$ACTIVE" &&
   $(timeout 15s git -c "safe.directory=$ACTIVE" -C "$ACTIVE" rev-parse HEAD) == "$RESEARCH_EXPECTED_ACTIVE_HEAD" &&
   $(timeout 15s git -c "safe.directory=$ACTIVE" -C "$ACTIVE" remote get-url origin) == "$RESEARCH_REMOTE" &&
   $(timeout 15s git -c "safe.directory=$RELEASE" -C "$RELEASE" remote get-url origin) == "$RESEARCH_REMOTE" ]]
python3 - "$ACTIVE" "$RELEASE" "$RESEARCH_WORK_PARENT" "$RESEARCH_CHECKOUT_PARENT" <<'PY'
import pathlib,sys
active,release,work,checkout = map(lambda p: pathlib.Path(p).resolve(strict=True),sys.argv[1:])
for parent in (work,checkout):
    for repo in (active,release):
        assert parent != repo and not parent.is_relative_to(repo) and not repo.is_relative_to(parent), 'Output overlaps active/release checkout'
PY
# Original captured hashes, not today's active settings alone, anchor active inputs.
python3 - "$RESEARCH_ORIGINAL_EVIDENCE/active-inputs.sha256" "$RESEARCH_ACTIVE_SETTINGS" \
  "$ACTIVE/.env" "$ACTIVE/config/config.yaml" <<'PY'
import pathlib, re, sys
manifest = pathlib.Path(sys.argv[1]); assert manifest.stat().st_size <= 4096
lines = manifest.read_text().splitlines()
assert len(lines) == 3 and all(re.fullmatch(r'[0-9a-f]{64}  /[^\n]+', line) for line in lines)
assert {line[66:] for line in lines} == set(sys.argv[2:]), 'Original active-input paths mismatch'
PY
timeout 180s sha256sum -c --status "$RESEARCH_ORIGINAL_EVIDENCE/active-inputs.sha256"
python3 - "$RESEARCH_ORIGINAL_EVIDENCE/candidate-config.sha256" \
  "$RESEARCH_CONFIG_DIR/.env" "$RESEARCH_CONFIG_DIR/config.yaml" <<'PY'
import pathlib, re, sys
manifest = pathlib.Path(sys.argv[1]); assert manifest.stat().st_size <= 4096
lines = manifest.read_text().splitlines()
assert len(lines) == 2 and all(re.fullmatch(r'[0-9a-f]{64}  /[^\n]+', line) for line in lines)
assert {line[66:] for line in lines} == set(sys.argv[2:]), 'Original candidate-config paths mismatch'
PY
timeout 180s sha256sum -c --status "$RESEARCH_ORIGINAL_EVIDENCE/candidate-config.sha256"
[[ -f $RESEARCH_CONFIG_DIR/.env && -f $RESEARCH_CONFIG_DIR/config.yaml ]]
timeout 60s cmp -s -- "$RESEARCH_CONFIG_DIR/.env" "$RELEASE/.env"
timeout 60s cmp -s -- "$RESEARCH_CONFIG_DIR/config.yaml" "$RELEASE/config/config.yaml"
VOLUME=${PROJECT}_signal_desk_data
VOLUME_ID=$(timeout 15s docker volume inspect --format '{{.Mountpoint}}|{{.CreatedAt}}' "$VOLUME")
[[ $VOLUME_ID == "$(<"$RESEARCH_ORIGINAL_EVIDENCE/active-volume-id.txt")" && $VOLUME_ID == *'|'* ]]
VOLUME_MOUNT=${VOLUME_ID%%|*}; RAW=$VOLUME_MOUNT/raw
[[ $VOLUME_MOUNT == /* && -d $RAW && ! -L $RAW ]]
API_ID=$(<"$RESEARCH_ORIGINAL_EVIDENCE/active-api-id.txt")
API_IMAGE=$(<"$RESEARCH_ORIGINAL_EVIDENCE/active-api-image.txt")
[[ $API_ID =~ ^[0-9a-f]{64}$ && $API_IMAGE =~ ^sha256:[0-9a-f]{64}$ ]]
python3 - "$RAW" "$VOLUME_MOUNT" "$RESEARCH_WORK_PARENT" "$RESEARCH_CHECKOUT_PARENT" <<'PY'
import pathlib,sys
raw,volume,*parents = map(lambda p: pathlib.Path(p).resolve(),sys.argv[1:])
for p in parents:
    for other in (raw,volume):
        assert p != other and not p.is_relative_to(other) and not other.is_relative_to(p), 'Output overlaps source volume'
PY
no_host_collector() {
  ps -eo args= | python3 -c 'import sys; needle="signal_desk.collector."+"binance_collector"; assert not any(needle in x for x in sys.stdin), "Host collector process detected"'
}
no_other_volume_users() {
  python3 - "$VOLUME" "$VOLUME_MOUNT" "$API_ID" "$API_IMAGE" <<'PY'
import json, pathlib, subprocess, sys
volume, mount, api, image = sys.argv[1:]; root = pathlib.Path(mount).resolve()
ids = subprocess.check_output(['docker','ps','-q','--no-trunc'],text=True,timeout=15).splitlines()
assert api in ids, 'Pinned API not running'
for cid in ids:
    info = json.loads(subprocess.check_output(['docker','inspect',cid],text=True,timeout=15))[0]
    if cid == api:
        assert info.get('Id') == api and info.get('Image') == image and info.get('State', {}).get('Running') is True, 'Pinned API identity changed'
        assert info.get('State', {}).get('Health', {}).get('Status') == 'healthy', 'Pinned API unhealthy'
        config = info.get('Config', {})
        assert config.get('Entrypoint') in (None, []) and config.get('Cmd') == [
            'python', '-m', 'signal_desk.api.health_server', '--host', '0.0.0.0', '--port', '8080'], 'Unknown API process'
    labels = info.get('Config',{}).get('Labels') or {}
    cmd = ' '.join(map(str, info.get('Config',{}).get('Cmd') or []))
    assert labels.get('com.docker.compose.service') != 'collector' and 'signal_desk.collector.'+'binance_collector' not in cmd, 'Collector running'
    for item in info['Mounts']:
        source = pathlib.Path(item['Source']).resolve()
        touches = (source == root or source.is_relative_to(root) or root.is_relative_to(source))
        if item.get('Name') == volume or touches:
            # The deployed Compose API has a writable /data mount. Its pinned
            # image and exact health-only command are required; idle/FD checks
            # are snapshots, NOT adversarial isolation or a TOCTOU guarantee.
            # Operator attests a controlled host interval: source idle and no
            # docker exec or privileged writer capable of changing the source.
            assert cid == api and (item.get('RW') is False or
                (item.get('Destination') == '/data' and item.get('Name') == volume)), 'Unknown writable source-volume mount'
PY
}
no_host_volume_writers() {
  # Best-effort instantaneous /proc snapshot, not a proof against a writer racing
  # between scans. Unreadable live fd/fdinfo or scan exhaustion fails closed.
  timeout 30s python3 - "$VOLUME_MOUNT" <<'PY'
import os, pathlib, sys
root = pathlib.Path(sys.argv[1]).resolve(strict=True)
proc = pathlib.Path('/proc')
pids = [p for p in proc.iterdir() if p.name.isdecimal()]
assert len(pids) <= 16384, 'PID scan budget exceeded'
checked = 0
for pid in pids:
    try:
        fds = list((pid/'fd').iterdir())
    except FileNotFoundError:
        continue  # Process exited while enumerating.
    for fd in fds:
        checked += 1
        assert checked <= 131072, 'FD scan budget exceeded'
        try:
            target = os.readlink(fd)
            if target.startswith(('socket:', 'pipe:', 'anon_inode:', 'memfd:')):
                continue
            if target.endswith(' (deleted)'):
                target = target[:-10]
            path = pathlib.Path(target).resolve(strict=False)
            if path != root and not path.is_relative_to(root):
                continue
            lines = (pid/'fdinfo'/fd.name).read_text().splitlines()
            flags = [line.split(':',1)[1].strip() for line in lines if line.startswith('flags:')]
            assert len(flags) == 1, 'Writable FD flags unavailable'
            assert int(flags[0], 8) & os.O_ACCMODE == os.O_RDONLY, 'Host process holds writable source-volume FD'
        except FileNotFoundError:
            continue  # Descriptor closed or process exited during inspection.
PY
}
verify_active() {
  [[ $(stat -c %s "$RESEARCH_PRIOR_EVIDENCE/active-head.txt") -le 128 &&
     $(stat -c %s "$RESEARCH_CANDIDATE_SETTINGS") -le 4194304 &&
     $(stat -c %s "$RESEARCH_ORIGINAL_EVIDENCE/active-inputs.sha256") -le 4096 &&
     $(stat -c %s "$RESEARCH_ORIGINAL_EVIDENCE/candidate-config.sha256") -le 4096 &&
     $(<"$RESEARCH_PRIOR_EVIDENCE/active-head.txt") == "$RESEARCH_EXPECTED_ACTIVE_HEAD" &&
     $(sha256sum "$RESEARCH_CANDIDATE_SETTINGS" | cut -d' ' -f1) == "$RESEARCH_APPROVAL_SHA256" &&
     $(timeout 15s git -c "safe.directory=$ACTIVE" -C "$ACTIVE" rev-parse HEAD) == "$RESEARCH_EXPECTED_ACTIVE_HEAD" &&
     $(timeout 15s docker inspect --format '{{.Id}}|{{.Image}}|{{.State.Running}}|{{.State.Health.Status}}' "$API_ID") == "$API_ID|$API_IMAGE|true|healthy" &&
     $(timeout 15s docker ps -q --no-trunc --filter "label=com.docker.compose.project=$PROJECT" --filter label=com.docker.compose.service=api) == "$API_ID" &&
     $(timeout 15s docker volume inspect --format '{{.Mountpoint}}|{{.CreatedAt}}' "$VOLUME") == "$VOLUME_ID" ]] &&
  timeout 180s sha256sum -c --status "$RESEARCH_ORIGINAL_EVIDENCE/active-inputs.sha256" &&
  timeout 180s sha256sum -c --status "$RESEARCH_ORIGINAL_EVIDENCE/candidate-config.sha256" &&
  timeout 60s cmp -s -- "$RESEARCH_CONFIG_DIR/.env" "$RELEASE/.env" &&
  timeout 60s cmp -s -- "$RESEARCH_CONFIG_DIR/config.yaml" "$RELEASE/config/config.yaml" &&
  timeout 180s python3 "$RESEARCH_GUARD" verify --settings "$RESEARCH_ACTIVE_SETTINGS" >/dev/null &&
  timeout 180s python3 "$RESEARCH_GUARD" verify --settings "$RESEARCH_CANDIDATE_SETTINGS" >/dev/null &&
  no_host_collector && no_other_volume_users && no_host_volume_writers
}
verify_active
# No output path is created until the existing source and host checks above pass.
RUN=$(mktemp -d "$RESEARCH_WORK_PARENT/research-$SID.XXXXXXXX")
# Private reproducibility record: exact reviewed procedure bytes, selected
# operator inputs and terminal output. Never place these host values in Git.
install -m 0600 -- "$SCRIPT" "$RUN/reviewed-procedure.sh"
python3 - "$RUN/operator-context.json" "$SCRIPT" "$HELPER" "$OUTPUT_GATES" <<'PY'
import hashlib, json, os, pathlib, sys
names = ('RESEARCH_RECOVERY_EVIDENCE', 'RESEARCH_ORIGINAL_EVIDENCE',
         'RESEARCH_WORK_PARENT', 'RESEARCH_CHECKOUT_PARENT', 'RESEARCH_REMOTE',
         'RESEARCH_IMAGE_REPO', 'RESEARCH_ACTIVE_SETTINGS',
         'RESEARCH_CANDIDATE_SETTINGS', 'RESEARCH_GUARD',
         'RESEARCH_EXPECTED_HOST', 'RESEARCH_AGENT_NAME_FILTER',
         'RESEARCH_PRIOR_EVIDENCE', 'RESEARCH_CONFIG_DIR',
         'RESEARCH_EXPECTED_ACTIVE_HEAD', 'RESEARCH_APPROVAL_SHA256',
         'RESEARCH_SOURCE_IDLE_CONFIRMED', 'RESEARCH_BASE_IMAGE_ID')
record = {'reviewed_commit': '5696c6cd17c4dc808c7fd3e42c47fc131f3873f3',
          'script_sha256': hashlib.sha256(pathlib.Path(sys.argv[2]).read_bytes()).hexdigest(),
          'helper_sha256': hashlib.sha256(pathlib.Path(sys.argv[3]).read_bytes()).hexdigest(),
          'output_gates_sha256': hashlib.sha256(pathlib.Path(sys.argv[4]).read_bytes()).hexdigest(),
          'command': 'bash ' + sys.argv[2],
          'operator_inputs': {name: os.environ[name] for name in names}}
fd = os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
with os.fdopen(fd, 'w') as out:
    json.dump(record, out, sort_keys=True)
    out.write('\n')
    out.flush()
    os.fsync(out.fileno())
PY
: > "$RUN/operator.log"
exec > >(tee -a "$RUN/operator.log") 2>&1
CURRENT_CIDFILE=''; CURRENT_NAME=''; IMAGE_ID=''; OUTPUT_ID=''
verify_source() {
  timeout 1800s python3 "$HELPER" verify --recovery "$RESEARCH_RECOVERY_EVIDENCE" \
    --original "$RESEARCH_ORIGINAL_EVIDENCE" --raw-dir "$RAW" --output "$1" \
    --expected-approval-sha256 "$RESEARCH_APPROVAL_SHA256"
}
finish() {
  local rc=$? cid found quarantine
  trap - EXIT INT TERM
  if [[ -n $CURRENT_CIDFILE ]]; then
    if [[ -f $CURRENT_CIDFILE && ! -L $CURRENT_CIDFILE ]]; then
      cid=$(<"$CURRENT_CIDFILE")
      if [[ $cid =~ ^[0-9a-f]{64}$ ]]; then
        found=$(timeout 10s docker inspect --format '{{.Id}}|{{.Image}}|{{index .Config.Labels "signal-desk.research.extract"}}|{{.Name}}|{{.State.Running}}' "$cid" 2>/dev/null || true)
        if [[ $found == "$cid|$IMAGE_ID|$SID|/$CURRENT_NAME|true" ]]; then
          if timeout 30s docker stop --time 20 "$cid" >>"$RUN/cleanup.log" 2>&1; then
            found=$(timeout 10s docker inspect --format '{{.Id}}|{{.Image}}|{{index .Config.Labels "signal-desk.research.extract"}}|{{.Name}}|{{.State.Running}}' "$cid" 2>/dev/null || true)
            [[ $found == "$cid|$IMAGE_ID|$SID|/$CURRENT_NAME|false" ]] || {
              echo 'Container stop state unconfirmed; inspect CID file' >&2; rc=1;
            }
          else echo 'Container stop unconfirmed; inspect CID file' >&2; rc=1; fi
        elif [[ $found != "$cid|$IMAGE_ID|$SID|/$CURRENT_NAME|false" ]]; then
          echo 'Container identity unconfirmed; no unrelated container stopped' >&2; rc=1
        fi
      else echo 'Container ID unconfirmed; inspect CID file' >&2; rc=1; fi
    else echo 'CID file absent; inspect Docker for residual container' >&2; rc=1; fi
  fi
  if ! verify_active || ! verify_source "$RUN/source-after.json"; then
    echo 'Active identity, original evidence or source changed / verification inconclusive' >&2
    rc=1
  elif [[ -f $RUN/source-before.json ]]; then
    python3 - "$RUN/source-before.json" "$RUN/source-after.json" <<'PY' || rc=1
import json,sys
before,after = (json.load(open(p)) for p in sys.argv[1:])
for field in ('source_files','expected_counts','expected_feature_sha256'):
    assert before.get(field) == after.get(field), 'Source evidence changed'
PY
  fi
  # Only quarantine this invocation's freshly created output inode, after
  # container identity/stop handling. A same-filesystem rename retains every
  # partial byte but removes the apparently usable output/prefix path.
  if ((rc)) && [[ -n $OUTPUT_ID ]]; then
    if [[ -d $RUN/output && ! -L $RUN/output &&
          $(stat -c '%d:%i' -- "$RUN/output" 2>/dev/null) == "$OUTPUT_ID" ]]; then
      quarantine="$RUN/incomplete-output"
      if [[ -e $quarantine || -L $quarantine ]]; then
        quarantine=$(mktemp -d "$RUN/incomplete-output.XXXXXXXX") && quarantine="$quarantine/output" || {
          echo 'Quarantine reservation failed; output still present for inspection' >&2
          exit 1
        }
      fi
      if mv -T -- "$RUN/output" "$quarantine"; then
        echo "Unvalidated extraction bytes quarantined at $quarantine" >&2
      else
        echo 'Quarantine rename failed; output still present for inspection' >&2
      fi
    else
      echo 'Fresh output identity unconfirmed; not moving unknown directory' >&2
    fi
  fi
  if ((rc)); then echo "RESEARCH_EXTRACTION_INCOMPLETE; preserve $RUN and any CID for inspection" >&2
  else echo "RESEARCH_PREFIX_EXTRACTED; inspect $RUN (not soak acceptance or trading approval)"; fi
  exit "$rc"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
verify_source "$RUN/source-before.json"
verify_active
# Helper copies exactly the four verified raw files; never chmod the source.
timeout 1800s python3 "$HELPER" copy --verified "$RUN/source-before.json" \
  --raw-dir "$RAW" --copy-dir "$RUN/raw-copy" --manifest-out "$RUN/completed.json"
verify_active
# Work and checkout are separate root-only protected parents, not agent mounts.
CHECKOUT=$(mktemp -d "$RESEARCH_CHECKOUT_PARENT/research-checkout.XXXXXXXX")
timeout 1800s git clone --no-local --no-checkout -- "$RESEARCH_REMOTE" "$CHECKOUT/tree" >"$RUN/clone.log" 2>&1
timeout 120s git -c "safe.directory=$CHECKOUT/tree" -C "$CHECKOUT/tree" checkout --detach "$PIN" >>"$RUN/clone.log" 2>&1
[[ $(timeout 15s git -c "safe.directory=$CHECKOUT/tree" -C "$CHECKOUT/tree" rev-parse HEAD) == "$PIN" &&
   -z $(timeout 15s git -c "safe.directory=$CHECKOUT/tree" -C "$CHECKOUT/tree" status --porcelain --untracked-files=all) ]]
timeout 180s python3 "$RESEARCH_GUARD" check-checkout --dir "$CHECKOUT/tree" \
  --commit "$PIN" --config-dir "$RESEARCH_CONFIG_DIR" \
  --agent-container "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["agent_container_id"])' "$RESEARCH_ACTIVE_SETTINGS")" \
  --project "$PROJECT" --settings "$RESEARCH_ACTIVE_SETTINGS"
verify_active
[[ $(timeout 15s docker image inspect --format '{{.Id}}' python:3.12-slim) == "$RESEARCH_BASE_IMAGE_ID" ]] || {
  echo 'Cached Python base image differs from operator pin' >&2; exit 2;
}
TAG="$RESEARCH_IMAGE_REPO:${PIN:0:12}-research-$(date -u +%Y%m%dT%H%M%S)-$$"
[[ -z $(timeout 15s docker image ls -q "$TAG") ]] || { echo 'Image tag already exists' >&2; exit 2; }
timeout --signal=INT --kill-after=30s 3600s docker build --pull=false -t "$TAG" "$CHECKOUT/tree" >"$RUN/build.log" 2>&1
[[ $(timeout 15s docker image inspect --format '{{.Id}}' python:3.12-slim) == "$RESEARCH_BASE_IMAGE_ID" ]] || {
  echo 'Cached Python base changed during build' >&2; exit 2;
}
IMAGE_ID=$(timeout 15s docker image inspect --format '{{.Id}}' "$TAG")
[[ $IMAGE_ID =~ ^sha256:[0-9a-f]{64}$ &&
   $(timeout 15s docker image inspect --format '{{.Id}}' "$IMAGE_ID") == "$IMAGE_ID" ]]
# Do not start an untracked inspection container: the only container invocation
# below performs extraction. Retain immutable image identity/layers, reviewed checkout
# inputs and build log. Apt/pip resolution remains non-hermetic; review manually.
timeout 15s docker image inspect --format '{{json .RootFS.Layers}}' "$IMAGE_ID" >"$RUN/image-layers.json"
python3 - "$RUN/build-provenance.json" "$RESEARCH_BASE_IMAGE_ID" "$IMAGE_ID" "$PIN" "$RUN" "$CHECKOUT/tree" <<'PY'
import hashlib, json, pathlib, sys
out, base, image, commit, run, checkout = sys.argv[1:]
root = pathlib.Path(run)
def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as source:
        while chunk := source.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()
record = {'commit': commit, 'cached_base_tag': 'python:3.12-slim',
          'base_image_id': base, 'built_image_id': image,
          'dependency_resolution': 'non-hermetic apt and pip; operator review required',
          'build_log_sha256': digest(root/'build.log'),
          'dockerfile_sha256': digest(pathlib.Path(checkout)/'Dockerfile'),
          'requirements_sha256': digest(pathlib.Path(checkout)/'requirements.txt'),
          'image_layers_sha256': digest(root/'image-layers.json')}
pathlib.Path(out).write_text(json.dumps(record, sort_keys=True) + '\n')
PY
echo "Review $RUN/build-provenance.json, build.log and image-layers.json before extraction."
echo "Provenance SHA-256: $(sha256sum "$RUN/build-provenance.json" | cut -d' ' -f1)"
[[ -r /dev/tty ]] || { echo 'Interactive trusted terminal required for build review' >&2; exit 2; }
read -r -p 'Type reviewed provenance SHA-256: ' RESEARCH_BUILD_PROVENANCE_REVIEWED </dev/tty
[[ $RESEARCH_BUILD_PROVENANCE_REVIEWED == "$(sha256sum "$RUN/build-provenance.json" | cut -d' ' -f1)" ]] || {
  echo 'Build provenance not approved' >&2; exit 2;
}
verify_active
CURRENT_NAME="research-prefix-${SID:0:8}-$$"
CURRENT_CIDFILE="$RUN/$CURRENT_NAME.cid"
mkdir -- "$RUN/output"
OUTPUT_ID=$(stat -c '%d:%i' -- "$RUN/output")
[[ -z $(timeout 15s docker ps -aq --filter "name=^/${CURRENT_NAME}$") && ! -e $CURRENT_CIDFILE ]]
# Only extraction: image ID, no network, read-only root and source, private writable result.
# The research-input-v1.json manifest is accepted only after the host output gate.
# Manifest has a dedicated target under an existing image directory; if the
# engine cannot mount that file, Docker fails closed without touching source.
# Retain all logs and partial bytes (quarantined on failure); never touch services.
if timeout --signal=INT --kill-after=20s 960s docker run --name "$CURRENT_NAME" \
  --cidfile "$CURRENT_CIDFILE" --label "signal-desk.research.extract=$SID" \
  --network none --read-only --restart no --memory 768m --cpus 0.75 --pids-limit 64 \
  --env PYTHONDONTWRITEBYTECODE=1 \
  --mount "type=bind,source=$RUN/raw-copy,target=/source,readonly" \
  --mount "type=bind,source=$RUN/completed.json,target=/app/docs/research/completed-raw-copy-v1.json,readonly" \
  --mount "type=bind,source=$RUN/output,target=/result" \
  "$IMAGE_ID" python -u -m signal_desk.research.extract_prefix \
  --raw-dir /source --source-manifest /app/docs/research/completed-raw-copy-v1.json \
  --spec /app/docs/research/s1_experiment_v1.json --output-dir /result/prefix \
  >"$RUN/extract.stdout.log" 2>"$RUN/extract.stderr.log"; then
  ( ulimit -v 2097152
    timeout 1200s python3 "$OUTPUT_GATES" validate --output "$RUN/output" \
      --source-manifest "$RUN/completed.json" --raw-copy-dir "$RUN/raw-copy" \
      --spec "$CHECKOUT/tree/docs/research/s1_experiment_v1.json" )
else
  echo 'Extraction failed or timed out; partial output and logs retained' >&2
  exit 1
fi
verify_active
