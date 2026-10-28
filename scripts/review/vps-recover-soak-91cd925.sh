#!/usr/bin/env bash
# REVIEW ONLY: prepare existing-session diagnostics for a separately approved root operator.
# Never run through the restricted SSH gateway. No capture, delete, rebuild or deploy.
set -Eeuo pipefail
umask 077
unset PYTHONPATH PYTHONHOME PYTHONOPTIMIZE
[[ $(id -u) -eq 0 ]] || { echo 'Trusted root terminal required' >&2; exit 1; }
CANDIDATE=91cd925d90bcc0f07d57b064dd180bc945c4602c
SID=cb8a0767d7284b8aaa3d09fbca7095f2
SCRIPT=$(realpath -e -- "${BASH_SOURCE[0]}")
STAGE=${SCRIPT%/*}
GATES=$STAGE/soak_recovery_gates.py
SOAK_GATES=$STAGE/soak_gates.py
BASE_GATES=$STAGE/acceptance_gates.py
[[ $(sha256sum "$SOAK_GATES" | cut -d' ' -f1) == ad19e237bc6c816a1a218cf269fdfce06248c693a95437016bedba2ef34a09a4 &&
   $(sha256sum "$BASE_GATES" | cut -d' ' -f1) == 575571200739f6d3aeacb22aba7faa09e3b855449872cb7484ca891f49fe6a48 ]]
required=(RECOVERY_ORIGINAL_EVIDENCE RECOVERY_EVIDENCE_PARENT RECOVERY_ACTIVE_SETTINGS
  RECOVERY_CANDIDATE_SETTINGS RECOVERY_GUARD RECOVERY_EXPECTED_HOST
  RECOVERY_AGENT_NAME_FILTER RECOVERY_PRIOR_EVIDENCE RECOVERY_CONFIG_DIR
  RECOVERY_REMOTE RECOVERY_IMAGE_REPO RECOVERY_EXPECTED_ACTIVE_HEAD
  RECOVERY_EXPECTED_CANDIDATE_APPROVAL_SHA256)
for key in "${required[@]}"; do
  [[ -n ${!key:-} ]] || { printf 'Missing operator-reviewed parameter: %s\n' "$key" >&2; exit 2; }
done
ORIGINAL=$RECOVERY_ORIGINAL_EVIDENCE
PARENT=$RECOVERY_EVIDENCE_PARENT
ACTIVE_SETTINGS=$RECOVERY_ACTIVE_SETTINGS
CANDIDATE_SETTINGS=$RECOVERY_CANDIDATE_SETTINGS
GUARD=$RECOVERY_GUARD
PRIOR=$RECOVERY_PRIOR_EVIDENCE
CONFIG_DIR=$RECOVERY_CONFIG_DIR
[[ $RECOVERY_EXPECTED_HOST =~ ^[A-Za-z0-9._-]+$ &&
   $RECOVERY_AGENT_NAME_FILTER =~ ^[A-Za-z0-9_.-]+$ &&
   $RECOVERY_IMAGE_REPO =~ ^[a-z0-9][a-z0-9._-]*$ &&
   $RECOVERY_EXPECTED_ACTIVE_HEAD =~ ^[0-9a-f]{40}$ &&
   $RECOVERY_EXPECTED_CANDIDATE_APPROVAL_SHA256 =~ ^[0-9a-f]{64}$ ]]
for path in "$SCRIPT" "$GATES" "$SOAK_GATES" "$BASE_GATES" "$ORIGINAL" "$PARENT" \
            "$ACTIVE_SETTINGS" "$CANDIDATE_SETTINGS" "$GUARD" "$PRIOR" "$CONFIG_DIR"; do
  [[ $path == /* && ! -L $path ]] || { echo 'Absolute nonsymlink protected paths required' >&2; exit 2; }
done
# Check protected ancestry and require the new evidence parent to be disjoint
# from original evidence, staging and the approved release/settings tree.
python3 - "$SCRIPT" "$GATES" "$SOAK_GATES" "$BASE_GATES" "$ORIGINAL" "$PARENT" \
  "$ACTIVE_SETTINGS" "$CANDIDATE_SETTINGS" "$GUARD" "$PRIOR" "$CONFIG_DIR" <<'PY'
import pathlib, stat, sys
paths = [pathlib.Path(x) for x in sys.argv[1:]]
for path in paths:
    assert str(path) == str(path.resolve(strict=True)), 'Linked/noncanonical protected path'
    for part in (path, *path.parents):
        info = part.lstat()
        assert info.st_uid == 0 and not stat.S_ISLNK(info.st_mode) and not info.st_mode & 0o022, 'Unprotected path'
for path in paths[:4] + paths[6:9]:
    assert stat.S_ISREG(path.stat().st_mode), 'Required staged/settings/guard file missing'
for path in (paths[4], paths[5], paths[9], paths[10]):
    assert path.is_dir() and path.stat().st_mode & 0o077 == 0, 'Original/parent must be private'
original, parent, stage = paths[4], paths[5], paths[0].parent
for other in (original, stage, paths[6].parent, paths[7].parent, paths[9], paths[10]):
    assert parent != other and not parent.is_relative_to(other) and not other.is_relative_to(parent), 'Evidence parent overlaps protected input'
PY
[[ -f $ORIGINAL/raw-pre-capture.json && -f $ORIGINAL/candidate-image-id.txt &&
   -f $ORIGINAL/active-api-id.txt && -f $ORIGINAL/active-api-image.txt &&
   -f $ORIGINAL/active-volume-id.txt && -f $ORIGINAL/active-inputs.sha256 &&
   -f $ORIGINAL/candidate-config.sha256 && -f $PRIOR/active-head.txt &&
   -f $CONFIG_DIR/.env && -f $CONFIG_DIR/config.yaml ]]
mapfile -t active_fields < <(timeout 180s python3 "$GUARD" verify --settings "$ACTIVE_SETTINGS")
mapfile -t candidate_fields < <(timeout 180s python3 "$GUARD" verify --settings "$CANDIDATE_SETTINGS")
[[ ${#active_fields[@]} -eq 3 && ${#candidate_fields[@]} -eq 3 ]]
ACTIVE_REPO=${active_fields[0]}; PROJECT=${active_fields[1]}; HOST=${active_fields[2]}
RELEASE=${candidate_fields[0]}
[[ $PROJECT == "${candidate_fields[1]}" && $HOST == "${candidate_fields[2]}" &&
   $HOST == "$RECOVERY_EXPECTED_HOST" && $(hostname) == "$HOST" &&
   $RELEASE == /srv/* && $RELEASE != "$ACTIVE_REPO" ]]
[[ $(git -c "safe.directory=$RELEASE" -C "$RELEASE" rev-parse HEAD) == "$CANDIDATE" ]]
[[ $(stat -c %s "$PRIOR/active-head.txt") -le 128 &&
   $(<"$PRIOR/active-head.txt") == "$RECOVERY_EXPECTED_ACTIVE_HEAD" &&
   $(stat -c %s "$CANDIDATE_SETTINGS") -le 4194304 &&
   $(sha256sum "$CANDIDATE_SETTINGS" | cut -d' ' -f1) == "$RECOVERY_EXPECTED_CANDIDATE_APPROVAL_SHA256" ]]
[[ $(git -c "safe.directory=$ACTIVE_REPO" -C "$ACTIVE_REPO" rev-parse HEAD) == "$RECOVERY_EXPECTED_ACTIVE_HEAD" &&
   $(git -c "safe.directory=$RELEASE" -C "$RELEASE" remote get-url origin) == "$RECOVERY_REMOTE" &&
   $(git -c "safe.directory=$ACTIVE_REPO" -C "$ACTIVE_REPO" remote get-url origin) == "$RECOVERY_REMOTE" &&
   $CONFIG_DIR != "$ACTIVE_REPO" && $CONFIG_DIR != "$RELEASE" ]]
timeout 60s cmp -s -- "$CONFIG_DIR/.env" "$RELEASE/.env"
timeout 60s cmp -s -- "$CONFIG_DIR/config.yaml" "$RELEASE/config/config.yaml"
python3 - "$ORIGINAL" "$ACTIVE_SETTINGS" "$ACTIVE_REPO" "$CONFIG_DIR" <<'PY'
import pathlib, re, sys
original, settings, active, config = map(pathlib.Path, sys.argv[1:])
for name, expected in (
    ('active-inputs.sha256', {str(settings), str(active/'.env'), str(active/'config/config.yaml')}),
    ('candidate-config.sha256', {str(config/'.env'), str(config/'config.yaml')})):
    with (original/name).open('rb') as source:
        data = source.read(4097)
    assert len(data) <= 4096, 'Original config manifest byte cap exceeded'
    lines = data.decode('utf-8').splitlines()
    assert len(lines) == len(expected) and all(re.fullmatch(r'[0-9a-f]{64}  /[^\n]+', line) for line in lines)
    assert {line[66:] for line in lines} == expected, 'Original hash manifest path mismatch'
PY
timeout 180s sha256sum -c --status "$ORIGINAL/active-inputs.sha256"
timeout 180s sha256sum -c --status "$ORIGINAL/candidate-config.sha256"
IMAGE_ID=$(<"$ORIGINAL/candidate-image-id.txt")
IMAGE=$RECOVERY_IMAGE_REPO:${CANDIDATE:0:12}
[[ $IMAGE_ID =~ ^sha256:[0-9a-f]{64}$ &&
   $(docker image inspect --format '{{.Id}}' "$IMAGE") == "$IMAGE_ID" &&
   $(docker image inspect --format '{{.Id}}' "$IMAGE_ID") == "$IMAGE_ID" ]]
API_ID=$(<"$ORIGINAL/active-api-id.txt")
API_IMAGE=$(<"$ORIGINAL/active-api-image.txt")
[[ $API_ID =~ ^[0-9a-f]{64}$ && $API_IMAGE =~ ^sha256:[0-9a-f]{64}$ ]]
VOLUME=${PROJECT}_signal_desk_data
VOLUME_ID=$(docker volume inspect --format '{{.Mountpoint}}|{{.CreatedAt}}' "$VOLUME")
[[ $VOLUME_ID == "$(<"$ORIGINAL/active-volume-id.txt")" && $VOLUME_ID == *'|'* ]]
VOLUME_MOUNT=${VOLUME_ID%%|*}
RAW_DIR=$VOLUME_MOUNT/raw
[[ -d $RAW_DIR && ! -L $RAW_DIR && -d $VOLUME_MOUNT &&
   $(timeout 15s docker inspect --format '{{range .Mounts}}{{if eq .Destination "/data"}}{{println .Name .Source}}{{end}}{{end}}' "$API_ID") == "$VOLUME $VOLUME_MOUNT" ]]
python3 - "$PARENT" "$ORIGINAL" "$RELEASE" "$ACTIVE_REPO" "$VOLUME_MOUNT" <<'PY'
import pathlib, sys
parent, original, release, active, volume = (pathlib.Path(p).resolve() for p in sys.argv[1:])
for protected in (release, active, volume):
    if (parent == protected or parent.is_relative_to(protected) or
        protected.is_relative_to(parent) or original == protected or
        original.is_relative_to(protected) or protected.is_relative_to(original)):
        raise SystemExit('Evidence parent overlaps release, active checkout or raw volume')
PY
verify_active() {
  [[ $(stat -c %s "$ORIGINAL/active-inputs.sha256") -le 4096 &&
     $(stat -c %s "$ORIGINAL/candidate-config.sha256") -le 4096 &&
     $(stat -c %s "$PRIOR/active-head.txt") -le 128 &&
     $(<"$PRIOR/active-head.txt") == "$RECOVERY_EXPECTED_ACTIVE_HEAD" &&
     $(stat -c %s "$CANDIDATE_SETTINGS") -le 4194304 &&
     $(sha256sum "$CANDIDATE_SETTINGS" | cut -d' ' -f1) == "$RECOVERY_EXPECTED_CANDIDATE_APPROVAL_SHA256" ]] &&
  timeout 180s sha256sum -c --status "$ORIGINAL/active-inputs.sha256" &&
  timeout 180s sha256sum -c --status "$ORIGINAL/candidate-config.sha256" &&
  [[ $(timeout 15s git -c "safe.directory=$ACTIVE_REPO" -C "$ACTIVE_REPO" rev-parse HEAD) == "$RECOVERY_EXPECTED_ACTIVE_HEAD" ]] &&
  [[ $(timeout 15s git -c "safe.directory=$RELEASE" -C "$RELEASE" rev-parse HEAD) == "$CANDIDATE" ]] &&
  timeout 60s cmp -s -- "$CONFIG_DIR/.env" "$RELEASE/.env" &&
  timeout 60s cmp -s -- "$CONFIG_DIR/config.yaml" "$RELEASE/config/config.yaml" &&
  [[ $(timeout 15s docker inspect --format '{{.Id}}|{{.Image}}|{{.State.Running}}' "$API_ID") == "$API_ID|$API_IMAGE|true" ]] &&
  [[ $(timeout 15s docker ps -q --no-trunc --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=api') == "$API_ID" ]] &&
  [[ $(timeout 15s docker volume inspect --format '{{.Mountpoint}}|{{.CreatedAt}}' "$VOLUME") == "$VOLUME_ID" ]] &&
  [[ $(timeout 15s docker image inspect --format '{{.Id}}' "$IMAGE") == "$IMAGE_ID" ]] &&
  timeout 180s python3 "$GUARD" verify --settings "$ACTIVE_SETTINGS" >/dev/null &&
  timeout 180s python3 "$GUARD" verify --settings "$CANDIDATE_SETTINGS" >/dev/null
}
verify_active
# Only the active API may use this data volume; no collector or other writer.
python3 - "$VOLUME" "$API_ID" "$ORIGINAL" "$PARENT" "$STAGE" "$ACTIVE_SETTINGS" \
  "$CONFIG_DIR" "$PRIOR" "$RECOVERY_AGENT_NAME_FILTER" <<'PY'
import json, pathlib, subprocess, sys
volume, api, original, parent, stage, settings, config, prior, name_filter = sys.argv[1:]
agent = json.loads(pathlib.Path(settings).read_text())['agent_container_id']
protected = [pathlib.Path(p).resolve() for p in (original, parent, stage, config, prior)]
ids = [agent] + subprocess.check_output(['docker','ps','-aq','--filter',f'name={name_filter}'], text=True).splitlines()
for cid in set(ids):
    info = json.loads(subprocess.check_output(['docker', 'inspect', cid], text=True))[0]
    for mount in info['Mounts']:
        source = pathlib.Path(mount['Source']).resolve()
        for path in protected:
            if source == path or source.is_relative_to(path) or path.is_relative_to(source):
                raise SystemExit('Recovery evidence/staging overlaps agent mount')
for cid in subprocess.check_output(['docker','ps','-q'], text=True).splitlines():
    item = json.loads(subprocess.check_output(['docker','inspect',cid], text=True))[0]
    labels = item.get('Config',{}).get('Labels') or {}
    cmd = ' '.join(map(str, item.get('Config',{}).get('Cmd') or []))
    if labels.get('com.docker.compose.service') == 'collector' or 'signal_desk.collector.binance_collector' in cmd:
        raise SystemExit('Another collector is running')
    if item['Id'] != api and any(m.get('Type') == 'volume' and m.get('Name') == volume for m in item['Mounts']):
        raise SystemExit('Another container uses the data volume')
PY
no_host_collector() {
  ps -eo args= | python3 -c 'import sys; lines=sys.stdin.read().splitlines(); needle="signal_desk.collector."+"binance_collector"; assert not any(needle in x for x in lines), "Host collector process detected"'
}
no_host_collector
# No write occurs before artifact, paper-only, isolation and idle-collector checks.
RECOVERY=$(mktemp -d "$PARENT/recovery-$SID.XXXXXXXX")
CURRENT_NAME=''
CURRENT_CIDFILE=''
finish() {
  local rc=$? found cid
  trap - EXIT INT TERM
  if [[ -n $CURRENT_CIDFILE ]]; then
    if [[ -f $CURRENT_CIDFILE && ! -L $CURRENT_CIDFILE ]]; then
      cid=$(<"$CURRENT_CIDFILE")
      if [[ $cid =~ ^[0-9a-f]{64}$ ]]; then
        found=$(timeout 10s docker inspect --format '{{.Id}}|{{.Image}}|{{index .Config.Labels "signal-desk.soak.recovery"}}|{{.Name}}|{{.State.Running}}' "$cid" 2>/dev/null || true)
        if [[ $found == "$cid|$IMAGE_ID|$SID|/$CURRENT_NAME|true" ]]; then
          timeout 30s docker stop --time 20 "$cid" >/dev/null 2>&1 ||
            echo 'New read-only diagnostic container stop unconfirmed; inspect exact ID' >&2
        elif [[ $found != "$cid|$IMAGE_ID|$SID|/$CURRENT_NAME|false" ]]; then
          echo 'New read-only diagnostic container identity unconfirmed; inspect CID file before retry' >&2
        fi
      else
        echo 'New read-only diagnostic container ID unavailable; inspect before retry' >&2
      fi
    else
      echo 'No new container ID recorded; no container stopped; inspect before retry' >&2
    fi
  fi
  date -u +%Y-%m-%dT%H:%M:%SZ > "$RECOVERY/end-utc.txt" || true
  if ! verify_active || ! timeout 1800s python3 "$GATES" verify-original \
      --original "$ORIGINAL" --manifest "$RECOVERY/original-evidence.sha256"; then
    echo 'Original evidence or active/candidate identity changed or verification inconclusive' >&2
    rc=1
  fi
  if ((rc)); then
    echo 'RECOVERY_DIAGNOSTICS_FAILED; keep all original and new evidence for operator inspection' >&2
  else
    echo 'RECOVERY_DIAGNOSTICS_OK; stored-session checks only; soak completion remains unverified'
  fi
  exit "$rc"
}
trap finish EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
# Freeze the original evidence file set in a distinct private directory.
timeout 1800s python3 "$GATES" freeze-original --original "$ORIGINAL" \
  --output "$RECOVERY/original-evidence.sha256"
timeout 1800s python3 "$GATES" verify-original --original "$ORIGINAL" \
  --manifest "$RECOVERY/original-evidence.sha256"
date -u +%Y-%m-%dT%H:%M:%SZ > "$RECOVERY/start-utc.txt"
timeout 1800s python3 "$GATES" derive --raw-dir "$RAW_DIR" \
  --pre-inventory "$ORIGINAL/raw-pre-capture.json" --session-id "$SID" \
  --output "$RECOVERY/derived-counts.json"
mapfile -t counts < <(python3 - "$RECOVERY/derived-counts.json" <<'PY'
import json, sys
v=json.load(open(sys.argv[1])); assert v['session_id']=='cb8a0767d7284b8aaa3d09fbca7095f2'
for key in ('book_snapshot','book_delta','trade'): print(v['counts'][key])
PY
)
[[ ${#counts[@]} -eq 3 && ${counts[0]} == 1 && ${counts[1]} =~ ^[1-9][0-9]*$ &&
   ${counts[2]} =~ ^[1-9][0-9]*$ ]]
timeout 1800s python3 "$GATES" freeze-raw --raw-dir "$RAW_DIR" \
  --output "$RECOVERY/raw-before.sha256"
DATA_READ_MOUNT="type=volume,source=$VOLUME,target=/data,readonly"
run_readonly() {
  local label=$1 budget=$2 name existing
  shift 2
  name="recovery-${SID:0:8}-${label}-$$"
  existing=$(timeout 15s docker ps -aq --filter "name=^/${name}$") || return 1
  [[ -z $existing ]] || return 1
  no_host_collector
  CURRENT_NAME=$name
  CURRENT_CIDFILE="$RECOVERY/$name.cid"
  [[ ! -e $CURRENT_CIDFILE && ! -L $CURRENT_CIDFILE ]] || return 1
  if timeout --signal=INT --kill-after=20s "$budget" docker run --name "$name" \
      --cidfile "$CURRENT_CIDFILE" --label "signal-desk.soak.recovery=$SID" \
      --network none --read-only --restart no \
      --memory 768m --cpus 0.75 --pids-limit 64 --env PYTHONDONTWRITEBYTECODE=1 \
      --mount "$DATA_READ_MOUNT" "$IMAGE_ID" "$@"; then
    CURRENT_CIDFILE=''
    CURRENT_NAME=''
  else
    return 1
  fi
}
run_readonly audit 3600s python -u -m signal_desk.tools.audit_raw \
  --raw-dir /data/raw --session-id "$SID" --expected-snapshots "${counts[0]}" \
  --expected-depth "${counts[1]}" --expected-trades "${counts[2]}" > "$RECOVERY/audit.json"
for run in 1 2; do
  run_readonly "replay-$run" 3600s python -u -m signal_desk.replay.session \
    --raw-dir /data/raw --session-id "$SID" --expected-snapshots "${counts[0]}" \
    --expected-depth "${counts[1]}" --expected-trades "${counts[2]}" \
    --max-runtime-seconds 3300 > "$RECOVERY/replay-$run.json"
done
timeout 1800s python3 "$GATES" verify-raw --raw-dir "$RAW_DIR" \
  --manifest "$RECOVERY/raw-before.sha256"
timeout 1800s python3 "$GATES" verify --raw-dir "$RAW_DIR" --summary "$RECOVERY/derived-counts.json" \
  --audit "$RECOVERY/audit.json" --replay-one "$RECOVERY/replay-1.json" \
  --replay-two "$RECOVERY/replay-2.json" --manifest "$RECOVERY/raw-before.sha256" \
  --output "$RECOVERY/diagnostics.json"
timeout 1800s python3 "$GATES" verify-raw --raw-dir "$RAW_DIR" \
  --manifest "$RECOVERY/raw-before.sha256"
verify_active
no_host_collector
