# Existing-session raw COPY and offline prefix extraction — operator review

**Proposed only; not executed.** This procedure consumes the already reported
recovery diagnostics for session `cb8a0767d7284b8aaa3d09fbca7095f2`. It does
not rerun capture, audit, replay, strategy diagnostics, training or deployment.
Do not invoke it through the restricted gateway. It requires a separately
approved trusted root terminal with access to the private recovery evidence.
This repository has not inspected that evidence or the VPS. A passing stored-data
recovery diagnostic is **not** full soak acceptance: resource sampling and
independent session-completion proof remain incomplete (`soak_acceptance=false`).
The proposed `completed:true` in `completed-raw-copy-v1` means the **copy**
finished and passed file verification; it must not be represented as proof that
the collector completed its planned duration.

## Source of truth and gates

Use the immutable merged research commit
`5696c6cd17c4dc808c7fd3e42c47fc131f3873f3`, not the older
`91cd925d90bcc0f07d57b064dd180bc945c4602c` candidate image (which lacks
the extractor). Before any copy, check the original recovery evidence's frozen
file set and hashes, `diagnostics.json`, `derived-counts.json`,
`operator-counts-compared.json`, `raw-before.sha256`, `audit.json`, both replay
JSONs and the current-baseline provenance. Require four recognized day-level
raw files whose whole-file names, byte sizes, line counts and SHA-256 values
agree across recovery evidence and the unchanged source. These files may include
other sessions; never infer full-file counts from the selected session totals.
Require the reported 1 snapshot + 35,936 depth + 222,238 trades = 258,175
ordered records; two matching replay hashes and 258,114 ready features each;
feature-output SHA-256
`bafabf00f920c948a7f952425d105197039af0104c0b28b65904afdbe94bf6c0`.
Reject a missing, changed or additional recognized raw file, disagreement in
any audit/replay inventory, a missing diagnostic gate or acceptance asserted as
true. Check the original evidence again after copying and after extraction.

The operator-reported collector `raw_bytes=547115599` is a storage total,
**not** the exact size of the four recognized source files. The procedure must
sum the actual sizes bound to the verified recovery raw hash manifest and refuse
an aggregate above 768 MiB (805,306,368 bytes) *before* scanning or copying.
No raw-data hash, basename, host path, approval hash or image ID is supplied by
this public document. Reviewed code-file digests below are not approval or raw
evidence. Raw evidence and host values must come from the private operator
record and fresh read-only checks; do not substitute a guessed value. Source
files must never be chmodded, moved, truncated, deleted or rewritten. Copy
original bytes into a fresh private directory outside the live volume,
approved releases and agent mounts, hash/check the copy against recovery
evidence, then remove write bits from the **copy only**. Preserve any partial
directory on failure and never retry over it. The private manifest must label
the operator report separately from what the copy verifier observed.

Require no active collector or other data-volume writer, including host processes
and containers not part of the Compose project. Verify approved active identity
and volume identity with the installed guard. The known active API may remain
running only if it is the pinned API image/ID running the known health-server
command with no observed writable source-volume FD; its Compose mount is
normally read-write, so checks of current FDs alone are not proof of quiescence.
An unexpected command, mount, writer or inconclusive check fails closed.
The root operator must establish an exclusive host-writer-control interval for
the entire verification, copy and extraction: no collector, other source-volume
writer, or privileged `docker exec`/root actor may open the API's writable mount
for writing. The script checks current processes, Docker consumers and writable
FDs at repeated points and rehashes source, but these are snapshots, not an
adversarial writer lock; a later writer or writable memory mapping can evade
them. If the trusted operator cannot establish this interval, **do not run the
procedure or treat a result as completed**. The manual idle attestation is a
precondition, not machine proof. Do not stop
unrelated services to satisfy the gate. Protect all staging, copy, checkout,
manifest, output and log paths with root ownership, private modes, no symlinked
ancestors, and disjointness from agent mounts and the live volume. Recheck source
and active identities after the operation; ordinary identity/hash checks are not
an adversarial host-writer sandbox.

## Proposed root-terminal staging and invocation (not run here)

The root operator must first obtain the **merge commit of this reviewed PR**
and the SHA-256 of the three committed review artifacts (script, evidence gate,
and output gate). A draft head is not an approved/merged execution source. The
staging block below is a template: every `RESEARCH_*` value and `REVIEWED_*`
hash comes from the private operator record; no placeholders are approved
values. The operator must independently verify the trusted repository origin
and the installed guard, read the whole script, and ensure each selected
root-only directory is outside current and replacement agent mounts *before
creating anything*. The root operator must establish exclusive writer control
and keep the source idle through staging and any later invocation. Staging
alone does not authorize running the procedure.

```bash
# Trusted root terminal ONLY; do not paste placeholder values or run this PR.
set -Eeuo pipefail
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
unset BASH_ENV ENV PYTHONPATH PYTHONHOME PYTHONOPTIMIZE
[[ $(id -u) == 0 ]]
umask 077
: "${REVIEWED_MERGE_SHA:?verified 40-character merge commit required}"
: "${REVIEWED_SCRIPT_SHA256:?verified committed script hash required}"
: "${REVIEWED_HELPER_SHA256:?verified committed helper hash required}"
: "${REVIEWED_OUTPUT_GATE_SHA256:?verified committed output gate hash required}"
: "${RESEARCH_STAGE_PARENT:?existing protected root-only parent required}"
: "${RESEARCH_REMOTE:?operator-reviewed GitHub origin required}"
: "${RESEARCH_ORIGINAL_EVIDENCE:?private original evidence required}"
: "${RESEARCH_RECOVERY_EVIDENCE:?private recovery evidence required}"
: "${RESEARCH_WORK_PARENT:?existing private evidence parent required}"
: "${RESEARCH_CHECKOUT_PARENT:?existing root-only checkout parent required}"
: "${RESEARCH_ACTIVE_SETTINGS:?installed approval settings required}"
: "${RESEARCH_CANDIDATE_SETTINGS:?installed candidate settings required}"
: "${RESEARCH_GUARD:?installed root-owned verifier required}"
: "${RESEARCH_EXPECTED_HOST:?trusted host identity required}"
: "${RESEARCH_AGENT_NAME_FILTER:?reviewed current/replacement agent filter required}"
: "${RESEARCH_IMAGE_REPO:?unique research-only image repository required}"
: "${RESEARCH_BASE_IMAGE_ID:?operator-approved cached python:3.12-slim image ID required}"
: "${RESEARCH_PRIOR_EVIDENCE:?private prior acceptance evidence required}"
: "${RESEARCH_CONFIG_DIR:?protected candidate configuration directory required}"
: "${RESEARCH_EXPECTED_ACTIVE_HEAD:?independently recorded active HEAD required}"
: "${RESEARCH_APPROVAL_SHA256:?operator-approved CURRENT candidate digest required}"
: "${RESEARCH_SOURCE_IDLE_CONFIRMED:?explicit collector-stopped/source-idle declaration required}"
[[ $REVIEWED_MERGE_SHA =~ ^[0-9a-f]{40}$ &&
   $REVIEWED_SCRIPT_SHA256 =~ ^[0-9a-f]{64}$ &&
   $REVIEWED_HELPER_SHA256 =~ ^[0-9a-f]{64}$ &&
   $REVIEWED_OUTPUT_GATE_SHA256 =~ ^[0-9a-f]{64}$ &&
   $RESEARCH_BASE_IMAGE_ID =~ ^sha256:[0-9a-f]{64}$ &&
   $RESEARCH_SOURCE_IDLE_CONFIRMED == operator-verified-exclusive-writer-control-and-source-idle ]]
# Values must already be loaded from the protected operator record; export only
# these reviewed inputs for the separate script process (never paste them in Git).
export RESEARCH_RECOVERY_EVIDENCE RESEARCH_ORIGINAL_EVIDENCE RESEARCH_WORK_PARENT \
  RESEARCH_CHECKOUT_PARENT RESEARCH_REMOTE RESEARCH_IMAGE_REPO RESEARCH_BASE_IMAGE_ID \
  RESEARCH_ACTIVE_SETTINGS RESEARCH_CANDIDATE_SETTINGS RESEARCH_GUARD \
  RESEARCH_EXPECTED_HOST RESEARCH_AGENT_NAME_FILTER RESEARCH_PRIOR_EVIDENCE \
  RESEARCH_CONFIG_DIR RESEARCH_EXPECTED_ACTIVE_HEAD RESEARCH_APPROVAL_SHA256 \
  RESEARCH_SOURCE_IDLE_CONFIRMED
timeout 180s python3 "$RESEARCH_GUARD" verify --settings "$RESEARCH_ACTIVE_SETTINGS" >/dev/null
timeout 180s python3 "$RESEARCH_GUARD" verify --settings "$RESEARCH_CANDIDATE_SETTINGS" >/dev/null
# Check the staging parent BEFORE creating it: trusted root, canonical, private,
# no symlinked/writable ancestors, and outside both current/replacement agent mounts.
python3 - "$RESEARCH_STAGE_PARENT" "$RESEARCH_ACTIVE_SETTINGS" "$RESEARCH_AGENT_NAME_FILTER" \
  "$RESEARCH_ORIGINAL_EVIDENCE" "$RESEARCH_RECOVERY_EVIDENCE" \
  "$RESEARCH_WORK_PARENT" "$RESEARCH_CHECKOUT_PARENT" <<'PY'
import json, pathlib, stat, subprocess, sys
stage, settings, name_filter, *protected = sys.argv[1:]
p = pathlib.Path(stage)
assert p.is_absolute() and p == p.resolve(strict=True) and p.is_dir() and not p.stat().st_mode & 0o077
for part in (p, *p.parents):
    info = part.lstat()
    assert info.st_uid == 0 and not stat.S_ISLNK(info.st_mode) and not info.st_mode & 0o022
for other in protected:
    q = pathlib.Path(other).resolve(strict=True)
    assert p != q and not p.is_relative_to(q) and not q.is_relative_to(p)
with open(settings, 'rb') as source:
    config = json.load(source)
agent = config['agent_container_id']
ids = {agent, *subprocess.check_output(
    ['docker','ps','-aq','--filter',f'name={name_filter}'], text=True, timeout=15).splitlines()}
for cid in ids:
    item = json.loads(subprocess.check_output(['docker','inspect',cid], text=True, timeout=15))[0]
    for mount in item['Mounts']:
        q = pathlib.Path(mount['Source']).resolve(strict=True)
        assert p != q and not p.is_relative_to(q) and not q.is_relative_to(p)
PY
STAGE=$(mktemp -d "${RESEARCH_STAGE_PARENT}/research-extract.XXXXXXXX")
for file in vps-research-copy-extract.sh research_copy_gates.py \
  research_output_gates.py soak_recovery_gates.py soak_gates.py acceptance_gates.py; do
  curl -fsSLo "$STAGE/$file" \
    "https://raw.githubusercontent.com/aliercankonus/signal-desk-prediction/${REVIEWED_MERGE_SHA}/scripts/review/$file"
  chmod 0600 "$STAGE/$file"
done
printf '%s  %s\n' "$REVIEWED_SCRIPT_SHA256" "$STAGE/vps-research-copy-extract.sh" \
  "$REVIEWED_HELPER_SHA256" "$STAGE/research_copy_gates.py" \
  "$REVIEWED_OUTPUT_GATE_SHA256" "$STAGE/research_output_gates.py" \
  '4728798c9c8668375f793db906fe9277ad4bb409f9ddb99f2b3c8d477326a27f' "$STAGE/soak_recovery_gates.py" \
  'ad19e237bc6c816a1a218cf269fdfce06248c693a95437016bedba2ef34a09a4' "$STAGE/soak_gates.py" \
  '575571200739f6d3aeacb22aba7faa09e3b855449872cb7484ca891f49fe6a48' "$STAGE/acceptance_gates.py" | sha256sum -c --status
bash -n "$STAGE/vps-research-copy-extract.sh"
python3 - "$STAGE" <<'PY'
import pathlib, sys
for name in ('research_copy_gates.py', 'research_output_gates.py',
             'soak_recovery_gates.py', 'soak_gates.py', 'acceptance_gates.py'):
    path = pathlib.Path(sys.argv[1]) / name
    compile(path.read_bytes(), str(path), 'exec')
PY
printf 'staged only; procedure not run: %s\n' "$STAGE"
```

### Separate invocation — only after operator authorization

**STOP after staging.** Review the exact staged bytes and private inputs, and
obtain separate, explicit operator authorization. The root operator must retain
exclusive writer control and a source-idle interval through the entire run;
the earlier process/FD checks are snapshots, not a writer lock. Only after
operator authorization, in the **same trusted root terminal** with `STAGE` and
the validated exports still set, may the operator invoke the reviewed script.
Its interactive build-provenance review remains a separate pause *before*
extraction; authorization here does not preapprove the built image.

```bash
# Run only after separate operator authorization; never as part of staging.
[[ $RESEARCH_SOURCE_IDLE_CONFIRMED == operator-verified-exclusive-writer-control-and-source-idle ]]
[[ -n ${STAGE:-} && -f $STAGE/vps-research-copy-extract.sh ]]
bash "$STAGE/vps-research-copy-extract.sh"
```

`REVIEWED_MERGE_SHA`, all three reviewed file hashes and protected paths are
**unresolved until a future merge and operator inspection**. Stage the reviewed
helper beside the script; do not fetch `main` or use a mutable branch in its
place. The script must use a separate root-protected checkout at the pinned
research commit, check the operator-approved cached base-image ID before/after
the build, record the resulting image ID, layer inventory and build-input hashes
privately, and build a new research-only image tag without changing gateway
approvals or deployment tags. **The repository's Dockerfile is not a hermetic
build:** its `python:3.12-slim` tag and apt/pip package sources can change. The
operator must review the private base-image identity before authorizing the
procedure, then inspect the build log and provenance digest at the script's
interactive pause before extraction. The Git commit alone does not pin those
executable bytes. Do not describe the resulting image as bit-for-bit
reproducible without an independently reviewed artifact. Then run **only** the
extractor by immutable image ID. No Compose `up`, gateway `deploy`, collector,
replay or baseline runner call is authorized by this review. The build may need
ordinary package-fetch network; the extraction container itself must run with
`--network none`, read-only root filesystem and read-only input mounts, a
distinct writable output mount, no production volume/socket/config mount,
finite internal (900 seconds) and outer timeouts, explicit memory/CPU/PID
limits, and a unique tracked container ID.
On timeout, only the exact newly created identity-verified container may be
stopped; retain it, the partial output, private log, manifest and CID for
inspection. On failure, rename only this invocation's output into a private
`incomplete-output` quarantine so a runner cannot mistake a linked manifest
for accepted output; preserve all bytes. A missing or unverifiable ID requires
manual intervention, not a name-based stop or deletion.

The host output gate must verify the emitted prefix's exact bytes against the
read-only COPY, the sequence-1 selection, limits, source and experiment digests,
and manifest truncation/status before success is reported. It does not authorize
the baseline runner. The extracted prefix starts at `ingest_sequence=1` and
stops before 90,000 session
records or 128 MiB of complete serialized raw JSONL, and is explicitly truncated
from the captured session. The existing baseline/S1 runner limits are unchanged.
Do not run that runner here. A complete copy/verified prefix is not 60 days of
usable research data and does not certify a soak, model or PnL.
