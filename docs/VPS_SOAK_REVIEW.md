# Proposed 60-minute VPS candidate soak (review only)

**Not executed. Not a deployment or promotion authorization.** This procedure is
for a separately approved trusted VPS **root terminal**, never the restricted
agent SSH gateway. It reuses the previously protected candidate checkout,
configuration, approval record, candidate image and private acceptance evidence
for commit `91cd925d90bcc0f07d57b064dd180bc945c4602c`. It does **not** run
`prepare-host-release.sh`, clone, build, replace existing artifacts, deploy or
change active settings. A missing/mismatched artifact stops the procedure;
do not repair it silently or rebuild.

Review [`vps-soak-91cd925.sh`](../scripts/review/vps-soak-91cd925.sh) and
[`soak_gates.py`](../scripts/review/soak_gates.py) together. Stage their exact
bytes from the **merged review commit, after approval**, in a new root-owned
`0700` directory outside every agent mount; check the published SHA-256 for
both. Stage the existing `acceptance_gates.py` from the PR #9 merge
`d5bba53fc6709af43b3821691a273e9a4622a119` beside them and check its
pinned SHA-256 `575571200739f6d3aeacb22aba7faa09e3b855449872cb7484ca891f49fe6a48`.
The reviewed soak script itself checks that third helper hash. The new review
helpers are **not** expected in the approved candidate image or checkout.

Proposed **staging only**, after independent root-side path/mount checks and
separate approval (not run in this PR):

```bash
# In a trusted root terminal. Supply the exact approved full merge SHA and
# a preverified root-only parent outside every agent mount; do not guess either.
REVIEW_COMMIT='REPLACE_WITH_APPROVED_FULL_MERGE_SHA'
STAGE_PARENT='REPLACE_WITH_VERIFIED_PROTECTED_STAGE_PARENT'
[[ $REVIEW_COMMIT =~ ^[a-f0-9]{40}$ && -d $STAGE_PARENT && $STAGE_PARENT == /* ]] || exit 1
STAGE=$(mktemp -d "$STAGE_PARENT/soak-review.XXXXXXXX")
chmod 700 "$STAGE"
curl --fail --silent --show-error --location \
  "https://raw.githubusercontent.com/aliercankonus/signal-desk-prediction/$REVIEW_COMMIT/scripts/review/vps-soak-91cd925.sh" \
  --output "$STAGE/vps-soak-91cd925.sh"
curl --fail --silent --show-error --location \
  "https://raw.githubusercontent.com/aliercankonus/signal-desk-prediction/$REVIEW_COMMIT/scripts/review/soak_gates.py" \
  --output "$STAGE/soak_gates.py"
curl --fail --silent --show-error --location \
  "https://raw.githubusercontent.com/aliercankonus/signal-desk-prediction/d5bba53fc6709af43b3821691a273e9a4622a119/scripts/review/acceptance_gates.py" \
  --output "$STAGE/acceptance_gates.py"
chmod 600 "$STAGE"/*
printf '%s  %s\n' \
  1da064b19d73bfa61cfcf46f8e8179f99fb23e88baae93403a4abd7561c23315 "$STAGE/vps-soak-91cd925.sh" \
  ad19e237bc6c816a1a218cf269fdfce06248c693a95437016bedba2ef34a09a4 "$STAGE/soak_gates.py" \
  575571200739f6d3aeacb22aba7faa09e3b855449872cb7484ca891f49fe6a48 "$STAGE/acceptance_gates.py" \
  | sha256sum --check --status
bash -n "$STAGE/vps-soak-91cd925.sh"
python3 - "$STAGE/soak_gates.py" "$STAGE/acceptance_gates.py" <<'PY'
import ast, pathlib, sys
for name in sys.argv[1:]: ast.parse(pathlib.Path(name).read_text())
PY
# Stop here. No soak invocation is authorized by staging.
```

Hash mismatch, inaccessible immutable commit, unverified root parent or mount
overlap blocks staging. Do not fall back to a mutable branch or local checkout.

## Root-operator inputs (private; no values in Git)

Export these after independent read-only discovery and operator review. Never
paste settings, paths, host/container identities or logs into the PR; never
use `set -x`.

| Variable | Required existing value |
|---|---|
| `SOAK_REMOTE` | Trusted origin URL of both protected active and candidate checkouts. |
| `SOAK_GUARD` | Installed root-owned release verifier. |
| `SOAK_ACTIVE_SETTINGS` | Root-only active approval/settings JSON. |
| `SOAK_CANDIDATE_SETTINGS` | Existing root-only candidate approval JSON under the installed verifier's approved settings parent. |
| `SOAK_CONFIG_DIR` | **Existing** root-only candidate config staging directory from the prior acceptance run, containing `.env` and `config.yaml`. |
| `SOAK_PRIOR_EVIDENCE` | **Existing** private prior acceptance evidence directory, containing image ID, candidate-config and active-input hash manifests, active HEAD/API ID/API image/volume ID. |
| `SOAK_EVIDENCE_ROOT` | Existing protected, root-only parent for a **new** private soak evidence directory. Do not reuse the prior directory. |
| `SOAK_EXPECTED_HOST` | Independently confirmed host name, matching both approvals and `hostname`. |
| `SOAK_AGENT_NAME_FILTER` | Operator-reviewed agent container-name filter broad enough to cover replacements for mount-isolation checks. |
| `SOAK_IMAGE_REPO` | Existing candidate image repository used in the prior run; tag is the first 12 characters of the approved commit. |
| `SOAK_CONTAINER_PREFIX` | Short unique lowercase prefix for this run's one capture and read-only validation containers. |

The script verifies the installed guard against **both** approvals (approved
commit/code, root ownership, origin/volume identity, paper-only config and
`execution_enabled=false`), exact staged config bytes, prior manifests and
candidate image ID. It requires the same active API ID/image and volume
identity recorded in the prior run; verifies no running collector container,
other container using the volume, or host collector process; and confirms
protected evidence/staging/configuration is outside reviewed agent mounts. No previous
collector/container/file/volume is stopped, replaced or deleted. If these
read-only checks do not pass, stop and investigate before creating evidence or
capturing. The existing data volume must have enough free space under the
configured raw quota and disk-HALT threshold for the proposed hour; the
collector itself fails closed rather than deleting raw data.

After separate authorization, the operator would invoke the **staged** script
with `bash` in the trusted root terminal and the reviewed exports in scope.
That future invocation is not performed by this PR. The script creates a
unique 0700 private evidence directory, inventories historical raw files with
sizes, device/inode and SHA-256, then starts **one** uniquely named candidate
continuous collector by the recorded exact image ID. It uses `--restart no`,
`--memory 512m --cpus 0.75 --pids-limit 64`,
`--max-run-seconds 3600` and a `timeout 3900s docker wait` capture wall budget.
Resource samples use bounded Docker CLI calls every 15 seconds. A timeout or
failure makes a bounded stop attempt **only for this new candidate ID** and
attempts historical-prefix verification; failure to confirm stop/integrity
requires manual operator investigation before any retry. The candidate
container remains for inspection after exit.

Acceptance requires a `STOPPED/max_run_seconds_reached` result, container exit
0 without OOM, a live resource sample, positive depth/trade counts, one new
snapshot session, and **zero** gaps/reconnects. The helper derives expected
counts from the new/appended raw bytes and cross-checks the collector's final
status and STOPPED log; it refuses more than 2,000,000 captured records rather
than assuming an unbounded memory budget. The previous inventory's original
inodes must remain present, unshrunk and byte-identical for the original
length; only appends/new files are allowed. A post-capture complete SHA-256
manifest is frozen during the read-only verification phase (maximum 64 raw
JSONL files).

After the capture gates pass, every discovered session is audited against its recorded expected snapshots,
depth and trade counts. Two sequential read-only replays of each session
must verify every stored capture feature hash, match counts and full input
file hashes, each yield positive `ready_features`, and produce the same
`feature_sha256`. Each audit and each replay runs with network disabled,
read-only volume and root filesystem, 768 MiB memory, 0.75 CPU and 64 PIDs,
with a **3,600-second** outer wall budget; replay additionally enforces a
**3,300-second** internal runtime limit and its existing 256 MiB output-byte
limit. Budget/size exhaustion is failure, not evidence of parity. On a
one-off timeout, cleanup is bounded to the uniquely labeled candidate
container; an unresponsive daemon must be inspected by the operator.

The new root-only evidence retains UTC start/end and procedure-end times,
pre/post raw inventories and hashes, per-session expected counts and audit/
replay JSON, Docker resource samples/limits/state/exit/log, active/candidate
identity hashes, disk and memory snapshots, and failure diagnostics. Sampled
stats are **not** peak usage or p99 latency. This one-hour proposal does not
verify retention/restore, longer collection, model performance or economic
execution. The procedure rechecks active API ID/image/running state, active
settings and configuration hashes, approved candidate and image identity,
volume identity and unchanged raw manifest before reporting `SOAK_OK`.

Local review checks use `bash -n`, Python compilation, targeted regressions and
full pytest in the development worktree. These are **not** VPS measurements or
soak results. No host command, capture, deploy, promotion or deletion is
performed by this PR.
