#!/usr/bin/env bash
# REVIEW ONLY. Run in a trusted VPS root terminal only after operator approval.
set -Eeuo pipefail
umask 077
unset PYTHONPATH PYTHONHOME PYTHONOPTIMIZE
[[ $(id -u) -eq 0 ]] || { echo 'Root terminal required' >&2; exit 1; }
# Host-specific inputs are supplied privately by the root operator; never store values in Git.
required=(ACCEPT_REMOTE ACCEPT_GUARD ACCEPT_ACTIVE_SETTINGS ACCEPT_RELEASE_ROOT
  ACCEPT_CONFIG_ROOT ACCEPT_SETTINGS_ROOT ACCEPT_EVIDENCE_ROOT ACCEPT_EXPECTED_HOST
  ACCEPT_AGENT_NAME_FILTER ACCEPT_CONTAINER_PREFIX ACCEPT_IMAGE_REPO)
for name in "${required[@]}"; do
  [[ -n ${!name:-} ]] || { printf 'Missing reviewed parameter: %s\n' "$name" >&2; exit 2; }
done
[[ $ACCEPT_EXPECTED_HOST =~ ^[A-Za-z0-9._-]+$ &&
   $ACCEPT_AGENT_NAME_FILTER =~ ^[A-Za-z0-9_.-]+$ &&
   $ACCEPT_CONTAINER_PREFIX =~ ^[a-z][a-z0-9-]{0,30}$ &&
   $ACCEPT_IMAGE_REPO =~ ^[a-z0-9][a-z0-9._-]*$ ]] || { echo 'Invalid reviewed name' >&2; exit 2; }
SHA=91cd925d90bcc0f07d57b064dd180bc945c4602c
REMOTE=$ACCEPT_REMOTE
GUARD=$ACCEPT_GUARD
ACTIVE_SETTINGS=$ACCEPT_ACTIVE_SETTINGS
RELEASE=$ACCEPT_RELEASE_ROOT/$SHA
CONFIG_DIR=$ACCEPT_CONFIG_ROOT/$SHA
SETTINGS=$ACCEPT_SETTINGS_ROOT/$SHA.json
EVIDENCE_PARENT=$ACCEPT_EVIDENCE_ROOT
[[ $RELEASE == /srv/* && $SETTINGS == /etc/signal-desk/releases/* ]] || {
  echo 'Release/settings paths violate the installed guard policy' >&2; exit 2;
}
[[ -f $GUARD && -f $ACTIVE_SETTINGS && ! -L $GUARD && ! -L $ACTIVE_SETTINGS ]]
verified=$(python3 "$GUARD" verify --settings "$ACTIVE_SETTINGS")
mapfile -t fields <<< "$verified"
[[ ${#fields[@]} -eq 3 ]]
ACTIVE_REPO=${fields[0]}; PROJECT=${fields[1]}; EXPECTED_HOST=${fields[2]}
[[ $(hostname) == "$EXPECTED_HOST" && "$EXPECTED_HOST" == "$ACCEPT_EXPECTED_HOST" && "$ACTIVE_REPO" != "$RELEASE" ]]
[[ $(git -c "safe.directory=$ACTIVE_REPO" -C "$ACTIVE_REPO" remote get-url origin) == "$REMOTE" ]]
AGENT_ID=$(python3 - "$ACTIVE_SETTINGS" <<'PY'
import json, sys
print(json.load(open(sys.argv[1]))['agent_container_id'])
PY
)
[[ $AGENT_ID =~ ^[0-9a-f]{64}$ ]]
[[ ! -e $RELEASE && ! -L $RELEASE && ! -e $CONFIG_DIR && ! -L $CONFIG_DIR && ! -e $SETTINGS && ! -L $SETTINGS ]]
# Independent, trusted-root preflight BEFORE cloning or copying config. No candidate code runs.
python3 - "$RELEASE" "$CONFIG_DIR" "$SETTINGS" "$ACTIVE_REPO" "$AGENT_ID" "$EVIDENCE_PARENT" "$ACCEPT_AGENT_NAME_FILTER" "$GUARD" <<'PY'
import json, os, pathlib, stat, subprocess, sys
release, config, settings, active, agent, evidence = map(pathlib.Path, sys.argv[1:7])
agent_filter = sys.argv[7]
guard = pathlib.Path(sys.argv[8])
protected = (release, config, settings, evidence, guard, pathlib.Path('/etc/sudoers.d'))
for path in (*protected, active / '.env', active / 'config/config.yaml'):
    assert path.is_absolute() and str(path) == os.path.normpath(str(path)), path
    for item in (path, *path.parents):
        if not item.exists() and not item.is_symlink():
            continue
        info = item.lstat()
        assert info.st_uid == 0 and not stat.S_ISLNK(info.st_mode) and not info.st_mode & 0o022, item
for path in (active / '.env', active / 'config/config.yaml'):
    assert path.is_file() and not path.stat().st_mode & 0o077, path
ids = {str(agent)} | set(subprocess.check_output(['docker', 'ps', '-aq', '--filter', f'name={agent_filter}'], text=True).splitlines())
for identifier in ids:
    mounts = json.loads(subprocess.check_output(['docker', 'inspect', '--format', '{{json .Mounts}}', identifier], text=True))
    for mount in mounts:
        source = pathlib.Path(mount['Source']).resolve()
        for path in protected:
            target = path.resolve(strict=False)
            assert not (target == source or target.is_relative_to(source) or source.is_relative_to(target)), (source, target)
PY
OLD_SHA=$(git -c "safe.directory=$ACTIVE_REPO" -C "$ACTIVE_REPO" rev-parse HEAD)
[[ $OLD_SHA != "$SHA" ]]
API_ID=$(docker ps -q --filter "label=com.docker.compose.project=$PROJECT" --filter 'label=com.docker.compose.service=api')
[[ $API_ID =~ ^[0-9a-f]{12,64}$ ]]
API_ID=$(docker inspect --format '{{.Id}}' "$API_ID")
API_IMAGE=$(docker inspect --format '{{.Image}}' "$API_ID")
VOLUME=${PROJECT}_signal_desk_data
VOLUME_ID=$(docker volume inspect --format '{{.Mountpoint}}|{{.CreatedAt}}' "$VOLUME")
VOLUME_MOUNT=${VOLUME_ID%%|*}
[[ -d $VOLUME_MOUNT && $VOLUME_ID == *'|'* ]]
install -d -o root -g root -m 700 "$EVIDENCE_PARENT"
EVIDENCE=$(mktemp -d "$EVIDENCE_PARENT/$SHA.XXXXXXXX")
sha256sum "$ACTIVE_SETTINGS" "$ACTIVE_REPO/.env" "$ACTIVE_REPO/config/config.yaml" > "$EVIDENCE/active-inputs.sha256"
printf '%s\n' "$OLD_SHA" > "$EVIDENCE/active-head.txt"
printf '%s\n' "$API_ID" > "$EVIDENCE/active-api-id.txt"
printf '%s\n' "$API_IMAGE" > "$EVIDENCE/active-api-image.txt"
printf '%s\n' "$VOLUME_ID" > "$EVIDENCE/active-volume-id.txt"
df -PB1 "$VOLUME_MOUNT" > "$EVIDENCE/disk-before.txt"
free -b > "$EVIDENCE/memory-before.txt"
# Unique root-only config staging; never overwrite the active settings or old release.
install -d -o root -g root -m 700 "$CONFIG_DIR"
install -o root -g root -m 600 "$ACTIVE_REPO/.env" "$CONFIG_DIR/.env"
install -o root -g root -m 600 "$ACTIVE_REPO/config/config.yaml" "$CONFIG_DIR/config.yaml"
sha256sum "$CONFIG_DIR/.env" "$CONFIG_DIR/config.yaml" > "$EVIDENCE/candidate-config.sha256"
git clone --no-checkout -- "$REMOTE" "$RELEASE"
git -c "safe.directory=$RELEASE" -C "$RELEASE" checkout --detach "$SHA"
[[ $(git -c "safe.directory=$RELEASE" -C "$RELEASE" rev-parse HEAD) == "$SHA" ]]
[[ -z $(git -c "safe.directory=$RELEASE" -C "$RELEASE" status --porcelain --untracked-files=all) ]]
# Independent root-owned tree audit; do not execute candidate code before it passes.
python3 - "$RELEASE" <<'PY'
import os, pathlib, stat, sys
root = pathlib.Path(sys.argv[1])
for base, dirs, files in os.walk(root, followlinks=False):
    for path in (pathlib.Path(base), *(pathlib.Path(base) / name for name in dirs + files)):
        info = path.lstat()
        assert info.st_uid == 0 and not stat.S_ISLNK(info.st_mode) and not info.st_mode & 0o022, path
PY
cmp -s -- "$GUARD" "$RELEASE/scripts/host_release_guard.py"
bash -n "$RELEASE/scripts/prepare-host-release.sh"
bash "$RELEASE/scripts/prepare-host-release.sh" --dir "$RELEASE" --commit "$SHA" \
  --config-dir "$CONFIG_DIR" --agent-container "$AGENT_ID" --project "$PROJECT" \
  --expected-host "$EXPECTED_HOST" --settings "$SETTINGS"
python3 "$GUARD" verify --settings "$SETTINGS" >/dev/null
sha256sum -c --status "$EVIDENCE/active-inputs.sha256"
# Do NOT run install-host-gateway.sh, deploy.sh, compose up or gateway deploy.
cd "$RELEASE"
docker compose -p "$PROJECT" -f "$RELEASE/docker-compose.yml" config -q
IMAGE=$ACCEPT_IMAGE_REPO:${SHA:0:12}
[[ -z $(docker image ls -q "$IMAGE") ]] || { echo 'Candidate image tag already exists; stop' >&2; exit 1; }
docker build --tag "$IMAGE" "$RELEASE" 2>&1 | tee "$EVIDENCE/build.log"
docker image inspect --format '{{.Id}}' "$IMAGE" > "$EVIDENCE/candidate-image-id.txt"
CONFIG_MOUNT="type=bind,source=$RELEASE/config,target=/app/config,readonly"
DATA_MOUNT="type=volume,source=$VOLUME,target=/data"
DATA_READ_MOUNT="type=volume,source=$VOLUME,target=/data,readonly"
docker run --rm --network none --env-file "$RELEASE/.env" --env SIGNAL_DESK_CONFIG=/app/config/config.yaml --env PYTHONOPTIMIZE=0 \
  --mount "$CONFIG_MOUNT" "$IMAGE" python -m signal_desk.tools.validate_all --config config/config.yaml \
  2>&1 | tee "$EVIDENCE/validate.log"
docker run --rm --network none --env-file "$RELEASE/.env" --env SIGNAL_DESK_CONFIG=/app/config/config.yaml --env PYTHONOPTIMIZE=0 \
  --mount "$CONFIG_MOUNT" "$IMAGE" python -m pytest -q 2>&1 | tee "$EVIDENCE/pytest.log"
grep -Eq '(^|[[:space:]])140 passed([[:space:]]|,|$)' "$EVIDENCE/pytest.log" || {
  echo 'Expected 140 passing tests; stop' >&2; exit 1;
}
python3 "$GUARD" verify --settings "$SETTINGS" >/dev/null
# Fail if ANY running Compose collector exists, or any non-API container uses this data volume.
python3 - "$VOLUME" "$API_ID" <<'PY'
import json, subprocess, sys
volume, api = sys.argv[1:]
ids = subprocess.check_output(['docker', 'ps', '-q'], text=True).splitlines()
for cid in ids:
    data = json.loads(subprocess.check_output(['docker', 'inspect', cid], text=True))[0]
    labels = data.get('Config', {}).get('Labels') or {}
    cmd = ' '.join(str(x) for x in (data.get('Config', {}).get('Cmd') or []))
    if labels.get('com.docker.compose.service') == 'collector' or 'signal_desk.collector.binance_collector' in cmd:
        raise SystemExit('Another collector is running; stop without capture')
    if data['Id'] != api and any(m.get('Type') == 'volume' and m.get('Name') == volume for m in data['Mounts']):
        raise SystemExit('Non-API container using the data volume; stop')
print('No running collector or other volume user detected; root operator must review host processes too')
PY
# Host-process/manual review is required too; refuse to auto-stop any existing service.
ps -eo pid,args > "$EVIDENCE/host-processes-before.txt"
if grep -F 'signal_desk.collector.binance_collector' "$EVIDENCE/host-processes-before.txt"; then
  echo 'Host collector process observed; stop' >&2; exit 1
fi
PREVIOUS_SESSION=$(python3 - "$VOLUME_MOUNT/status/collector_status.json" <<'PY'
import json, pathlib, sys
p=pathlib.Path(sys.argv[1])
print(json.loads(p.read_text()).get('session_id', '') if p.is_file() else '')
PY
)
CAPTURE_ID=''
CAPTURE_COMPLETE=0
cleanup_on_failure() {
  rc=$?
  if ((rc != 0 && CAPTURE_COMPLETE == 0)) && [[ -n ${CAPTURE_ID:-} ]]; then
    docker logs "$CAPTURE_ID" > "$EVIDENCE/capture.log" 2>&1 || true
    docker stop --time 20 "$CAPTURE_ID" >/dev/null 2>&1 || true
    echo "Candidate capture failed; inspected/stopped only $CAPTURE_ID; evidence: $EVIDENCE" >&2
  fi
}
trap cleanup_on_failure EXIT
CAPTURE_NAME="$ACCEPT_CONTAINER_PREFIX-${SHA:0:12}-$(date -u +%Y%m%d%H%M%S)"
[[ -z $(docker ps -aq --filter "name=^/${CAPTURE_NAME}$") ]]
CAPTURE_ID=$(docker run -d --name "$CAPTURE_NAME" --network bridge \
  --memory 512m --cpus 0.75 --pids-limit 64 --restart no \
  --env-file "$RELEASE/.env" --env SIGNAL_DESK_CONFIG=/app/config/config.yaml --env PYTHONOPTIMIZE=0 \
  --mount "$CONFIG_MOUNT" --mount "$DATA_MOUNT" "$IMAGE" \
  python -u -m signal_desk.collector.binance_collector --mode stream \
  --max-events 1000 --config config/config.yaml)
[[ $CAPTURE_ID =~ ^[0-9a-f]{12,64}$ ]]
CAPTURE_ID=$(docker inspect --format '{{.Id}}' "$CAPTURE_ID")
[[ $CAPTURE_ID =~ ^[0-9a-f]{64}$ ]]
timeout 600s docker wait "$CAPTURE_ID" > "$EVIDENCE/capture-exit.txt" &
WAIT_PID=$!
while kill -0 "$WAIT_PID" 2>/dev/null; do
  docker stats --no-stream --format '{{json .}}' "$CAPTURE_ID" >> "$EVIDENCE/collector-stats.jsonl" 2>/dev/null || true
  sleep 1
done
wait "$WAIT_PID"
[[ $(tr -d '\r\n' < "$EVIDENCE/capture-exit.txt") == 0 ]]
docker logs "$CAPTURE_ID" > "$EVIDENCE/capture.log" 2>&1
docker inspect --format '{{json .State}}' "$CAPTURE_ID" > "$EVIDENCE/capture-state.json"
docker inspect --format 'Memory={{.HostConfig.Memory}} NanoCpus={{.HostConfig.NanoCpus}} PidsLimit={{.HostConfig.PidsLimit}}' \
  "$CAPTURE_ID" > "$EVIDENCE/capture-limits.txt"
python3 - "$EVIDENCE" "$PREVIOUS_SESSION" <<'PY'
import json, pathlib, re, sys
p=pathlib.Path(sys.argv[1]); prior=sys.argv[2]
state=json.loads((p/'capture-state.json').read_text())
assert state['Status']=='exited' and state['ExitCode']==0 and not state['OOMKilled']
lines=(p/'capture.log').read_text().splitlines()
summaries=[]
for line in lines:
    try: value=json.loads(line)
    except ValueError: continue
    if isinstance(value, dict) and 'written_events' in value: summaries.append(value)
assert len(summaries)==1, 'Expected exactly one completed capture summary'
s=summaries[0]; sid=s['session_id']
assert re.fullmatch(r'[0-9a-f]{32}', sid) and sid!=prior
assert s['status']=='ok' and s['written_events']==1000 and s['last_ingest_sequence']==1000
assert s['depth_events']>=1 and s['trade_events']>=0 and s['depth_events']+s['trade_events']==999
assert s['gap_count']==0 and s['ordering_version']=='session-applied-v1'
(p/'capture-summary.json').write_text(json.dumps({'session_id':sid,'book_snapshot':1,
    'book_delta':s['depth_events'],'trade':s['trade_events'],'records':1000},sort_keys=True)+'\n')
samples=[json.loads(line) for line in (p/'collector-stats.jsonl').read_text().splitlines() if line.strip()]
assert samples and any(x.get('MemUsage') and not x['MemUsage'].startswith('0B') for x in samples), 'No live resource sample'
print('New completed session and exact counts:',(p/'capture-summary.json').read_text().strip())
print('Live collector resource samples:',len(samples))
PY
CAPTURE_COMPLETE=1
# The capture has exited; only read-only audit/replay one-off containers follow.
read -r SESSION_ID SNAPSHOTS DEPTH_COUNT TRADE_COUNT < <(python3 - "$EVIDENCE/capture-summary.json" <<'PY'
import json,sys
v=json.load(open(sys.argv[1]))
print(v['session_id'],v['book_snapshot'],v['book_delta'],v['trade'])
PY
)
RAW_DIR=$VOLUME_MOUNT/raw
shopt -s nullglob
raw_files=( "$RAW_DIR"/binance_btcusdt_depth_*.jsonl "$RAW_DIR"/binance_btcusdt_trade_*.jsonl )
(( ${#raw_files[@]} > 0 && ${#raw_files[@]} <= 64 ))
sha256sum -- "${raw_files[@]}" > "$EVIDENCE/raw-before.sha256"
docker run --rm --network none --env-file "$RELEASE/.env" --env SIGNAL_DESK_CONFIG=/app/config/config.yaml --env PYTHONOPTIMIZE=0 \
  --mount "$CONFIG_MOUNT" --mount "$DATA_READ_MOUNT" "$IMAGE" python -u -m signal_desk.tools.audit_raw \
  --raw-dir /data/raw --session-id "$SESSION_ID" --expected-snapshots "$SNAPSHOTS" \
  --expected-depth "$DEPTH_COUNT" --expected-trades "$TRADE_COUNT" > "$EVIDENCE/raw-audit.json"
for run in 1 2; do
  docker run --rm --network none --env-file "$RELEASE/.env" --env SIGNAL_DESK_CONFIG=/app/config/config.yaml --env PYTHONOPTIMIZE=0 \
    --mount "$CONFIG_MOUNT" --mount "$DATA_READ_MOUNT" "$IMAGE" python -u -m signal_desk.replay.session \
    --raw-dir /data/raw --session-id "$SESSION_ID" --expected-snapshots "$SNAPSHOTS" \
    --expected-depth "$DEPTH_COUNT" --expected-trades "$TRADE_COUNT" > "$EVIDENCE/replay-$run.json"
done
python3 - "$EVIDENCE" "$SESSION_ID" "$SNAPSHOTS" "$DEPTH_COUNT" "$TRADE_COUNT" <<'PY'
import json, pathlib, re, sys
p=pathlib.Path(sys.argv[1]); sid=sys.argv[2]
expected={'book_snapshot':int(sys.argv[3]),'book_delta':int(sys.argv[4]),'trade':int(sys.argv[5])}
assert sum(expected.values())==1000
results=[json.loads((p/f'replay-{n}.json').read_text()) for n in (1,2)]
audit=json.loads((p/'raw-audit.json').read_text())
assert audit['status']=='ok' and audit['session_id']==sid and audit['counts']==expected and audit['selected_records']==1000
for r in results:
    assert r['status']=='ok' and r['session_id']==sid and r['counts']==expected
    assert r['records']==1000 and r['expected_counts_checked'] is True
    assert r['capture_hashes_verified']==1000 and r['last_ingest_sequence']==1000
    assert re.fullmatch(r'[0-9a-f]{64}',r['feature_sha256'])
assert results[0]['feature_sha256']==results[1]['feature_sha256']
assert results[0]['files']==results[1]['files']==audit['files'] or (
    {(f['file'],f['sha256'],f['bytes'],f['lines']) for f in results[0]['files']} ==
    {(f['file'],f['sha256'],f['bytes'],f['lines']) for f in results[1]['files']} ==
    {(f['file'],f['sha256'],f['bytes'],f['lines']) for f in audit['files']})
manifest={pathlib.Path(line[66:]).name:line[:64] for line in (p/'raw-before.sha256').read_text().splitlines()}
assert {f['file']:f['sha256'] for f in results[0]['files']}==manifest
print('Replay parity: 1000 hashes checked twice; feature_sha256 identical:',results[0]['feature_sha256'])
print('Input files with matching whole-file SHA-256:',len(manifest))
PY
sha256sum -c --status "$EVIDENCE/raw-before.sha256"
sha256sum -- "${raw_files[@]}" > "$EVIDENCE/raw-after.sha256"
cmp -s -- "$EVIDENCE/raw-before.sha256" "$EVIDENCE/raw-after.sha256"
df -PB1 "$VOLUME_MOUNT" > "$EVIDENCE/disk-after.txt"
free -b > "$EVIDENCE/memory-after.txt"
sha256sum -c --status "$EVIDENCE/active-inputs.sha256"
sha256sum -c --status "$EVIDENCE/candidate-config.sha256"
[[ $(git -c "safe.directory=$ACTIVE_REPO" -C "$ACTIVE_REPO" rev-parse HEAD) == "$OLD_SHA" ]]
[[ $(docker inspect --format '{{.Id}}' "$API_ID") == "$API_ID" ]]
[[ $(docker inspect --format '{{.Image}}' "$API_ID") == "$API_IMAGE" ]]
[[ $(docker inspect --format '{{.State.Running}}' "$API_ID") == true ]]
[[ $(docker volume inspect --format '{{.Mountpoint}}|{{.CreatedAt}}' "$VOLUME") == "$VOLUME_ID" ]]
python3 "$GUARD" verify --settings "$ACTIVE_SETTINGS" >/dev/null
python3 "$GUARD" verify --settings "$SETTINGS" >/dev/null
[[ -z $(docker ps -q --filter "id=$CAPTURE_ID") ]]
trap - EXIT
printf 'ACCEPTANCE_OK commit=%s evidence=%s; no API deploy or gateway promotion\n' "$SHA" "$EVIDENCE"
