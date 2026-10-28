#!/usr/bin/env bash
# REVIEW ONLY: proposed trusted VPS root-terminal procedure; never run via SSH gateway.
set -Eeuo pipefail
umask 077
unset PYTHONPATH PYTHONHOME PYTHONOPTIMIZE
[[ $(id -u) -eq 0 ]] || { echo 'Root terminal required' >&2; exit 1; }
SHA=91cd925d90bcc0f07d57b064dd180bc945c4602c
SCRIPT=$(realpath -e -- "${BASH_SOURCE[0]}")
SCRIPT_DIR=${SCRIPT%/*}
GATES=$SCRIPT_DIR/soak_gates.py
BASE_GATES=$SCRIPT_DIR/acceptance_gates.py
# The merged acceptance helper must be staged alongside the new reviewed pair.
BASE_GATES_SHA=575571200739f6d3aeacb22aba7faa09e3b855449872cb7484ca891f49fe6a48
required=(SOAK_REMOTE SOAK_GUARD SOAK_ACTIVE_SETTINGS SOAK_CANDIDATE_SETTINGS
  SOAK_CONFIG_DIR SOAK_PRIOR_EVIDENCE SOAK_EVIDENCE_ROOT SOAK_EXPECTED_HOST
  SOAK_AGENT_NAME_FILTER SOAK_IMAGE_REPO SOAK_CONTAINER_PREFIX)
for name in "${required[@]}"; do
  [[ -n ${!name:-} ]] || { printf 'Missing reviewed parameter: %s\n' "$name" >&2; exit 2; }
done
[[ $SOAK_EXPECTED_HOST =~ ^[A-Za-z0-9._-]+$ &&
   $SOAK_AGENT_NAME_FILTER =~ ^[A-Za-z0-9_.-]+$ &&
   $SOAK_IMAGE_REPO =~ ^[a-z0-9][a-z0-9._-]*$ &&
   $SOAK_CONTAINER_PREFIX =~ ^[a-z][a-z0-9-]{0,20}$ ]] || {
  echo 'Invalid reviewed name parameter' >&2; exit 2;
}
GUARD=$SOAK_GUARD
ACTIVE_SETTINGS=$SOAK_ACTIVE_SETTINGS
SETTINGS=$SOAK_CANDIDATE_SETTINGS
PRIOR=$SOAK_PRIOR_EVIDENCE
EVIDENCE_PARENT=$SOAK_EVIDENCE_ROOT
CONFIG_DIR=$SOAK_CONFIG_DIR
for path in "$SCRIPT" "$GATES" "$BASE_GATES" "$GUARD" "$ACTIVE_SETTINGS" "$SETTINGS" \
            "$PRIOR" "$EVIDENCE_PARENT" "$CONFIG_DIR"; do
  [[ $path == /* && ! -L $path ]] || { echo 'Absolute, nonsymlink protected paths required' >&2; exit 2; }
done
[[ $SETTINGS == /etc/signal-desk/releases/* && -d $PRIOR && -d $CONFIG_DIR &&
   -f $PRIOR/candidate-image-id.txt && -f $PRIOR/candidate-config.sha256 &&
   -f $PRIOR/active-inputs.sha256 && -d $EVIDENCE_PARENT ]] || {
  echo 'Existing approved artifacts and private evidence parent required' >&2; exit 2;
}
# Only the reviewed root-owned files/paths may be used; never use the agent checkout.
python3 - "$SCRIPT" "$GATES" "$BASE_GATES" "$GUARD" "$ACTIVE_SETTINGS" "$SETTINGS" \
  "$PRIOR" "$EVIDENCE_PARENT" "$CONFIG_DIR" <<'PY'
import pathlib, stat, sys
for raw in sys.argv[1:]:
    path = pathlib.Path(raw)
    assert str(path) == str(path.resolve(strict=True)), 'Noncanonical or linked path'
    for part in (path, *path.parents):
        info = part.lstat()
        assert info.st_uid == 0 and not stat.S_ISLNK(info.st_mode) and not info.st_mode & 0o022, 'Unprotected path'
    if path in map(pathlib.Path, sys.argv[1:7]):
        assert stat.S_ISREG(path.stat().st_mode), 'Staged file missing'
    if path in map(pathlib.Path, sys.argv[7:10]):
        assert path.is_dir() and path.stat().st_mode & 0o077 == 0, 'Private directory not root-only'
for raw in sys.argv[5:7]:
    assert pathlib.Path(raw).stat().st_mode & 0o077 == 0, 'Approval settings not root-only'
PY
[[ $(sha256sum "$BASE_GATES" | cut -d' ' -f1) == "$BASE_GATES_SHA" ]]
mapfile -t active_fields < <(python3 "$GUARD" verify --settings "$ACTIVE_SETTINGS")
mapfile -t candidate_fields < <(python3 "$GUARD" verify --settings "$SETTINGS")
[[ ${#active_fields[@]} -eq 3 && ${#candidate_fields[@]} -eq 3 ]]
ACTIVE_REPO=${active_fields[0]}; PROJECT=${active_fields[1]}; EXPECTED_HOST=${active_fields[2]}
RELEASE=${candidate_fields[0]}
[[ $PROJECT == "${candidate_fields[1]}" && $EXPECTED_HOST == "${candidate_fields[2]}" &&
   $EXPECTED_HOST == "$SOAK_EXPECTED_HOST" && $(hostname) == "$EXPECTED_HOST" &&
   $RELEASE == /srv/* && $RELEASE != "$ACTIVE_REPO" ]]
[[ $(git -c "safe.directory=$RELEASE" -C "$RELEASE" rev-parse HEAD) == "$SHA" ]]
[[ $(git -c "safe.directory=$RELEASE" -C "$RELEASE" remote get-url origin) == "$SOAK_REMOTE" &&
   $(git -c "safe.directory=$ACTIVE_REPO" -C "$ACTIVE_REPO" remote get-url origin) == "$SOAK_REMOTE" ]]
# The guard verifies approved code and paper-only settings. Check original staging too.
[[ -f $CONFIG_DIR/.env && -f $CONFIG_DIR/config.yaml &&
   $CONFIG_DIR != "$RELEASE" && $CONFIG_DIR != "$ACTIVE_REPO" ]]
cmp -s -- "$CONFIG_DIR/.env" "$RELEASE/.env"
cmp -s -- "$CONFIG_DIR/config.yaml" "$RELEASE/config/config.yaml"
python3 - "$PRIOR" "$ACTIVE_SETTINGS" "$ACTIVE_REPO" "$CONFIG_DIR" <<'PY'
import pathlib, re, sys
prior, settings, active, config = map(pathlib.Path, sys.argv[1:])
for name, wanted in (
    ('active-inputs.sha256', {str(settings), str(active/'.env'), str(active/'config/config.yaml')}),
    ('candidate-config.sha256', {str(config/'.env'), str(config/'config.yaml')})):
    lines = (prior/name).read_text().splitlines()
    assert len(lines) == len(wanted) and all(re.fullmatch(r'[0-9a-f]{64}  /[^\n]+', x) for x in lines)
    assert {x[66:] for x in lines} == wanted, 'Evidence manifest path mismatch'
PY
sha256sum -c --status "$PRIOR/active-inputs.sha256"
sha256sum -c --status "$PRIOR/candidate-config.sha256"
[[ $(git -c "safe.directory=$ACTIVE_REPO" -C "$ACTIVE_REPO" rev-parse HEAD) == "$(<"$PRIOR/active-head.txt")" ]]
IMAGE=$SOAK_IMAGE_REPO:${SHA:0:12}
IMAGE_ID=$(<"$PRIOR/candidate-image-id.txt")
[[ $IMAGE_ID =~ ^sha256:[0-9a-f]{64}$ && $(docker image inspect --format '{{.Id}}' "$IMAGE") == "$IMAGE_ID" &&
   $(docker image inspect --format '{{.Id}}' "$IMAGE_ID") == "$IMAGE_ID" ]]
API_ID=$(docker ps -q --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=api')
[[ $API_ID =~ ^[0-9a-f]{12,64}$ ]]
API_ID=$(docker inspect --format '{{.Id}}' "$API_ID")
API_IMAGE=$(docker inspect --format '{{.Image}}' "$API_ID")
[[ $API_ID == "$(<"$PRIOR/active-api-id.txt")" && $API_IMAGE == "$(<"$PRIOR/active-api-image.txt")" ]]
VOLUME=${PROJECT}_signal_desk_data
VOLUME_ID=$(docker volume inspect --format '{{.Mountpoint}}|{{.CreatedAt}}' "$VOLUME")
[[ $VOLUME_ID == "$(<"$PRIOR/active-volume-id.txt")" && $VOLUME_ID == *'|'* ]]
VOLUME_MOUNT=${VOLUME_ID%%|*}
[[ -d $VOLUME_MOUNT && $(docker inspect --format \
  '{{range .Mounts}}{{if eq .Destination "/data"}}{{println .Name .Source}}{{end}}{{end}}' "$API_ID") == "$VOLUME $VOLUME_MOUNT" ]]
# Check protected evidence/staging against all reviewed agent mounts; reject other writers.
python3 - "$VOLUME" "$API_ID" "$EVIDENCE_PARENT" "$PRIOR" "$SCRIPT_DIR" "$CONFIG_DIR" \
  "$SOAK_AGENT_NAME_FILTER" "$ACTIVE_SETTINGS" <<'PY'
import json, pathlib, subprocess, sys
volume, api, evidence, prior, staging, config, agent_filter, settings_path = sys.argv[1:]
agent = json.loads(pathlib.Path(settings_path).read_text())['agent_container_id']
ids = [agent] + subprocess.check_output(['docker','ps','-aq','--filter',f'name={agent_filter}'], text=True).splitlines()
protected = [pathlib.Path(p).resolve() for p in (evidence, prior, staging, config)]
for cid in set(ids):
    info = json.loads(subprocess.check_output(['docker','inspect',cid],text=True))[0]
    for mount in info['Mounts']:
        source = pathlib.Path(mount['Source']).resolve()
        for path in protected:
            if path == source or path.is_relative_to(source) or source.is_relative_to(path):
                raise SystemExit('Protected evidence/staging overlaps agent mount')
for cid in subprocess.check_output(['docker','ps','-q'],text=True).splitlines():
    info = json.loads(subprocess.check_output(['docker','inspect',cid],text=True))[0]
    labels = info.get('Config',{}).get('Labels') or {}
    command = ' '.join(map(str, info.get('Config',{}).get('Cmd') or []))
    if labels.get('com.docker.compose.service') == 'collector' or 'signal_desk.collector.binance_collector' in command:
        raise SystemExit('Another collector is running')
    if info['Id'] != api and any(m.get('Type') == 'volume' and m.get('Name') == volume for m in info['Mounts']):
        raise SystemExit('Another container uses the data volume')
PY
ps -eo args= | python3 -c 'import sys; lines=sys.stdin.read().splitlines(); needle="signal_desk.collector."+"binance_collector"; assert not any(needle in x for x in lines), "Host collector process detected"'
RAW_DIR=$VOLUME_MOUNT/raw
[[ -d $RAW_DIR ]]
# Do not create new evidence until every existing candidate/active identity gate passed.
EVIDENCE=$(mktemp -d "$EVIDENCE_PARENT/soak-$SHA.XXXXXXXX")
printf '%s\n' "$IMAGE_ID" > "$EVIDENCE/candidate-image-id.txt"
printf '%s\n' "$API_ID" > "$EVIDENCE/active-api-id.txt"
printf '%s\n' "$API_IMAGE" > "$EVIDENCE/active-api-image.txt"
printf '%s\n' "$VOLUME_ID" > "$EVIDENCE/active-volume-id.txt"
sha256sum "$ACTIVE_SETTINGS" "$ACTIVE_REPO/.env" "$ACTIVE_REPO/config/config.yaml" > "$EVIDENCE/active-inputs.sha256"
sha256sum "$CONFIG_DIR/.env" "$CONFIG_DIR/config.yaml" > "$EVIDENCE/candidate-config.sha256"
df -PB1 "$VOLUME_MOUNT" > "$EVIDENCE/disk-before.txt"
free -b > "$EVIDENCE/memory-before.txt"
timeout 1800s python3 "$BASE_GATES" inventory --raw-dir "$RAW_DIR" --output "$EVIDENCE/raw-pre-capture.json"
CAPTURE_ID=''
STATS_PID=''
CAPTURE_CLOSED=0
verify_active() {
  sha256sum -c --status "$EVIDENCE/active-inputs.sha256" &&
  sha256sum -c --status "$EVIDENCE/candidate-config.sha256" &&
  [[ $(git -c "safe.directory=$ACTIVE_REPO" -C "$ACTIVE_REPO" rev-parse HEAD) == "$(<"$PRIOR/active-head.txt")" ]] &&
  [[ $(timeout 15s docker inspect --format '{{.Id}}|{{.Image}}|{{.State.Running}}' "$API_ID") == "$API_ID|$API_IMAGE|true" ]] &&
  [[ $(timeout 15s docker ps -q --no-trunc --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=api') == "$API_ID" ]] &&
  [[ $(timeout 15s docker volume inspect --format '{{.Mountpoint}}|{{.CreatedAt}}' "$VOLUME") == "$VOLUME_ID" ]] &&
  timeout 180s python3 "$GUARD" verify --settings "$ACTIVE_SETTINGS" >/dev/null &&
  timeout 180s python3 "$GUARD" verify --settings "$SETTINGS" >/dev/null &&
  [[ $(timeout 15s docker image inspect --format '{{.Id}}' "$IMAGE") == "$IMAGE_ID" ]]
}
cleanup() {
  local rc=$?
  trap - EXIT INT TERM
  if [[ -n $STATS_PID ]]; then kill "$STATS_PID" 2>/dev/null || true; wait "$STATS_PID" 2>/dev/null || true; fi
  if [[ -n $CAPTURE_ID && $CAPTURE_CLOSED -eq 0 ]]; then
    local running
    running=$(timeout 10s docker inspect --format '{{.State.Running}}' "$CAPTURE_ID" 2>/dev/null || true)
    if [[ $running != false ]]; then
      timeout 30s docker stop --time 20 "$CAPTURE_ID" >/dev/null 2>&1 ||
        echo 'Candidate stop unconfirmed: operator must inspect exact ID' >&2
    fi
    timeout 20s docker logs "$CAPTURE_ID" > "$EVIDENCE/capture-failure.log" 2>&1 || true
    timeout 10s docker inspect --format '{{json .State}}' "$CAPTURE_ID" > "$EVIDENCE/capture-failure-state.json" 2>/dev/null || true
    timeout 1800s python3 "$BASE_GATES" verify-prefix --raw-dir "$RAW_DIR" \
      --inventory "$EVIDENCE/raw-pre-capture.json" --output "$EVIDENCE/raw-failure-prefix.json" ||
      echo 'Failure prefix verification inconclusive; inspect privately' >&2
  fi
  date -u +%Y-%m-%dT%H:%M:%SZ > "$EVIDENCE/procedure-end-utc.txt" || true
  df -PB1 "$VOLUME_MOUNT" > "$EVIDENCE/disk-after.txt" || true
  free -b > "$EVIDENCE/memory-after.txt" || true
  if ! verify_active; then
    echo 'Active/candidate identity verification failed or inconclusive' >&2
    rc=1
  fi
  if ((rc != 0)); then
    echo "SOAK_FAILED; private evidence retained: $EVIDENCE" >&2
  else
    printf 'SOAK_OK commit=%s; private evidence retained: %s; no API deploy or promotion\n' "$SHA" "$EVIDENCE"
  fi
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
verify_active
CAPTURE_NAME="$SOAK_CONTAINER_PREFIX-${SHA:0:12}-$(date -u +%Y%m%d%H%M%S)-$$"
[[ -z $(docker ps -aq --filter "name=^/${CAPTURE_NAME}$") ]]
CONFIG_MOUNT="type=bind,source=$RELEASE/config,target=/app/config,readonly"
DATA_MOUNT="type=volume,source=$VOLUME,target=/data"
DATA_READ_MOUNT="type=volume,source=$VOLUME,target=/data,readonly"
date -u +%Y-%m-%dT%H:%M:%SZ > "$EVIDENCE/start-utc.txt"
CAPTURE_ID=$(docker run -d --name "$CAPTURE_NAME" --network bridge --restart no \
  --stop-timeout 20 --memory 512m --cpus 0.75 --pids-limit 64 \
  --env-file "$RELEASE/.env" --env SIGNAL_DESK_CONFIG=/app/config/config.yaml \
  --env PYTHONOPTIMIZE=0 --mount "$CONFIG_MOUNT" --mount "$DATA_MOUNT" "$IMAGE_ID" \
  python -u -m signal_desk.collector.binance_collector --mode continuous \
  --max-run-seconds 3600 --config config/config.yaml)
[[ $CAPTURE_ID =~ ^[0-9a-f]{64}$ ]]
[[ $(docker inspect --format '{{.Id}}' "$CAPTURE_ID") == "$CAPTURE_ID" ]]
docker inspect --format '{{json .HostConfig}}' "$CAPTURE_ID" > "$EVIDENCE/capture-hostconfig.json"
python3 - "$EVIDENCE/capture-hostconfig.json" <<'PY'
import json, sys
v=json.load(open(sys.argv[1])); assert v['Memory']==536870912 and v['NanoCpus']==750000000
assert v['PidsLimit']==64 and v['RestartPolicy']['Name']=='no'
PY
sample_stats() {
  while [[ $(timeout 8s docker inspect --format '{{.State.Running}}' "$CAPTURE_ID" 2>/dev/null || true) == true ]]; do
    timeout 10s docker stats --no-stream --format '{{json .}}' "$CAPTURE_ID" \
      >> "$EVIDENCE/collector-stats.jsonl" 2>/dev/null || true
    sleep 15
  done
}
sample_stats & STATS_PID=$!
# Strict capture wall budget; on timeout the EXIT trap stops ONLY this candidate ID.
timeout 3900s docker wait "$CAPTURE_ID" > "$EVIDENCE/capture-exit.txt"
kill "$STATS_PID" 2>/dev/null || true
wait "$STATS_PID" 2>/dev/null || true
STATS_PID=''
date -u +%Y-%m-%dT%H:%M:%SZ > "$EVIDENCE/end-utc.txt"
[[ $(tr -d '\r\n' < "$EVIDENCE/capture-exit.txt") == 0 ]]
[[ $(timeout 10s docker inspect --format '{{.State.Running}}' "$CAPTURE_ID") == false ]]
timeout 30s docker logs "$CAPTURE_ID" > "$EVIDENCE/capture.log" 2>&1
timeout 10s docker inspect --format '{{json .State}}' "$CAPTURE_ID" > "$EVIDENCE/capture-state.json"
cp -- "$VOLUME_MOUNT/status/collector_status.json" "$EVIDENCE/collector-status.json"
# Original inodes and original-length hashes must be unchanged; allow append/new.
timeout 1800s python3 "$BASE_GATES" verify-prefix --raw-dir "$RAW_DIR" \
  --inventory "$EVIDENCE/raw-pre-capture.json" --output "$EVIDENCE/raw-post-capture-prefix.json"
CAPTURE_CLOSED=1
python3 "$GATES" summarize --raw-dir "$RAW_DIR" --pre-inventory "$EVIDENCE/raw-pre-capture.json" \
  --status "$EVIDENCE/collector-status.json" --log "$EVIDENCE/capture.log" \
  --state "$EVIDENCE/capture-state.json" --stats "$EVIDENCE/collector-stats.jsonl" \
  --output "$EVIDENCE/sessions.json"
shopt -s nullglob
raw_files=( "$RAW_DIR"/*.jsonl )
(( ${#raw_files[@]} > 0 && ${#raw_files[@]} <= 64 ))
sha256sum -- "${raw_files[@]}" > "$EVIDENCE/raw-before.sha256"
run_readonly() {
  local name=$1 budget=$2
  shift 2
  name="$SOAK_CONTAINER_PREFIX-${SHA:0:8}-${name}-$$"
  [[ -z $(docker ps -aq --filter "name=^/${name}$") ]] || return 1
  if timeout --signal=INT --kill-after=20s "$budget" docker run --rm --name "$name" \
    --label "signal-desk.soak.review=$SHA" --label "signal-desk.soak.name=$name" \
    --network none --read-only --restart no --memory 768m --cpus 0.75 --pids-limit 64 \
    --env PYTHONDONTWRITEBYTECODE=1 --mount "$DATA_READ_MOUNT" "$IMAGE_ID" "$@"; then
    return 0
  else
    local rc=$?
    local cleanup_id
    cleanup_id=$(timeout 10s docker inspect --format '{{.Id}}|{{.Image}}|{{index .Config.Labels "signal-desk.soak.name"}}' "$name" 2>/dev/null || true)
    if [[ $cleanup_id =~ ^([0-9a-f]{64})\|$IMAGE_ID\|$name$ ]]; then
      timeout 30s docker stop --time 20 "${BASH_REMATCH[1]}" >/dev/null 2>&1 ||
        echo 'Candidate read-only container stop unconfirmed; operator must inspect' >&2
    elif [[ -n $cleanup_id ]]; then
      echo 'Candidate read-only container identity changed; refusing cleanup' >&2
    else
      echo 'Candidate read-only container identity unconfirmed; operator must inspect before retry' >&2
    fi
    return "$rc"
  fi
}
# All sessions found by appended-byte scan are audited; zero reconnects entails exactly one.
SESSIONS=$(python3 "$GATES" list-sessions --summary "$EVIDENCE/sessions.json")
[[ -n $SESSIONS ]]
while read -r SID SNAPSHOTS DEPTH_COUNT TRADE_COUNT; do
  [[ $SID =~ ^[0-9a-f]{32}$ && $SNAPSHOTS =~ ^[0-9]+$ &&
     $DEPTH_COUNT =~ ^[0-9]+$ && $TRADE_COUNT =~ ^[0-9]+$ ]]
  run_readonly "audit-${SID:0:8}" 3600s python -u -m signal_desk.tools.audit_raw \
    --raw-dir /data/raw --session-id "$SID" --expected-snapshots "$SNAPSHOTS" \
    --expected-depth "$DEPTH_COUNT" --expected-trades "$TRADE_COUNT" > "$EVIDENCE/audit-$SID.json"
  for run in 1 2; do
    run_readonly "replay-$run-${SID:0:8}" 3600s python -u -m signal_desk.replay.session \
      --raw-dir /data/raw --session-id "$SID" --expected-snapshots "$SNAPSHOTS" \
      --expected-depth "$DEPTH_COUNT" --expected-trades "$TRADE_COUNT" \
      --max-runtime-seconds 3300 > "$EVIDENCE/replay-$SID-$run.json"
  done
  python3 "$GATES" verify-session --summary "$EVIDENCE/sessions.json" --session-id "$SID" \
    --audit "$EVIDENCE/audit-$SID.json" --replay-one "$EVIDENCE/replay-$SID-1.json" \
    --replay-two "$EVIDENCE/replay-$SID-2.json" --manifest "$EVIDENCE/raw-before.sha256" \
    --output "$EVIDENCE/session-check-$SID.json"
done <<< "$SESSIONS"
sha256sum -c --status "$EVIDENCE/raw-before.sha256"
sha256sum -- "${raw_files[@]}" > "$EVIDENCE/raw-after.sha256"
cmp -s -- "$EVIDENCE/raw-before.sha256" "$EVIDENCE/raw-after.sha256"
python3 "$GATES" verify-raw-set --raw-dir "$RAW_DIR" --manifest "$EVIDENCE/raw-before.sha256"
verify_active
