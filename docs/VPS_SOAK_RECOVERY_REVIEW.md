# Interrupted candidate soak: existing-session recovery review

**Draft only; not executed.** This is a review-only diagnostic path for the
already captured session `cb8a0767d7284b8aaa3d09fbca7095f2`. It does not
start a collector, repeat the 60-minute capture, change the active API,
deploy/promote/rebuild, remove containers, or delete or alter raw data or the
original soak evidence. The restricted SSH gateway is not an execution route.
Any future root-operator execution needs separate approval and exact private
inputs. No host evidence was available to this development checkout.

## Static investigation, not a host finding

The merged `vps-soak-91cd925.sh` starts the candidate capture, then requires a
normal duration stop, completed `STOPPED` status/log, prefix verification,
`soak_gates.py summarize`, audit and two matching replays. Its `set -Eeuo
pipefail`/EXIT trap retains failure evidence and exits if interrupted; it has
**no resume entry point**. It is unsafe to rerun it merely to audit an existing
session, because rerunning can start a **new** capture. From source alone we
cannot identify why the actual run was interrupted, whether the old capture
finished normally, whether this session is complete, whether the original
files are intact, or whether the active host is unchanged. The session ID is
supplied by the operator, not verified from private evidence here.

The new `vps-recover-soak-91cd925.sh` is a **different**, recovery-only proposed
root-terminal procedure. Its helper verifies the original pre-capture byte
prefixes/inodes, counts only appended records from this exact ordered session,
rejects incomplete tails/multiple sessions, freezes current raw-file hashes,
then compares one read-only raw audit and two read-only ordered replays. It
checks every captured feature hash and positive `ready_features` through the
existing replay/soak gates. Counts derived from raw data are **not independent
completion evidence**, even if a replay reports `expected_counts_checked`.
Before either audit or replay, the procedure must also match the separately
**operator-reported collector totals**: one snapshot, 35,936 depth deltas,
222,238 trades, 258,175 records. These figures were supplied for this review;
the assistant did **not** inspect host status or raw evidence to verify them.
An inconsistent reported total or any difference from raw-derived counts stops
the procedure. The comparison is stored with that provenance, not as a host
read-back or proof of capture completion.
The output says `RECOVERY_DIAGNOSTICS_OK`, never `SOAK_OK` or acceptance. A
partial/absent original pre-inventory, a changed original prefix, unsupported
ordering, count mismatch, hash mismatch or budget exhaustion blocks success;
never truncate, patch or repair original files to make it pass.

## Reviewed staging and private inputs — proposed only

Review the script and `soak_recovery_gates.py` from this PR **together**. After
merge and separate authorization, stage the two exact reviewed bytes from the
immutable merge commit beside `soak_gates.py` from PR #11's merge
`9e0e3eef5c5b701f5cdec2f00cdd37ef9ee2f957` and
`acceptance_gates.py` from PR #9's merge
`d5bba53fc6709af43b3821691a273e9a4622a119`, in a new protected
root-owned `0700` directory outside agent mounts. The older helper hashes are
`ad19e237bc6c816a1a218cf269fdfce06248c693a95437016bedba2ef34a09a4`
and `575571200739f6d3aeacb22aba7faa09e3b855449872cb7484ca891f49fe6a48`.
The script verifies these two older helper hashes. Verify the new script/helper
hashes from the reviewed PR before any later staging; a draft head is not a
merged, approved artifact. No staging or root command is run by this PR.

The future operator must supply these **existing**, independently verified
values in a trusted root terminal, without placing values, config or host IDs
in Git:

| Variable | Meaning |
|---|---|
| `RECOVERY_ORIGINAL_EVIDENCE` | Original private interrupted-soak evidence directory; leave untouched. Must contain the pre-capture inventory and recorded active/candidate identity files. |
| `RECOVERY_EVIDENCE_PARENT` | Separate pre-existing root-only parent, outside original evidence, releases, data volume and agent mounts, for a fresh recovery evidence directory. |
| `RECOVERY_ACTIVE_SETTINGS`, `RECOVERY_CANDIDATE_SETTINGS` | Installed guard's protected active and currently reviewed candidate approval JSON; paper mode and execution-disabled only. The candidate approval's historical bytes are not established. |
| `RECOVERY_GUARD` | Installed root-owned release verifier. |
| `RECOVERY_PRIOR_EVIDENCE`, `RECOVERY_CONFIG_DIR` | Original protected acceptance evidence (including active HEAD) and original staged candidate `.env`/config; both remain unchanged. |
| `RECOVERY_REMOTE`, `RECOVERY_IMAGE_REPO` | Independently reviewed repository URL and candidate image repository; both original Git origins and the immutable image tag/ID must match. |
| `RECOVERY_EXPECTED_ACTIVE_HEAD` | Independently recorded pre-interruption active commit from the protected prior acceptance record. |
| `RECOVERY_OPERATOR_APPROVED_CURRENT_APPROVAL_SHA256`, `RECOVERY_CURRENT_BASELINE_APPROVAL` | Digest of the **current** installed candidate approval, explicitly reviewed and approved by the root operator for recovery, and the exact declaration `operator-approved-current-recovery-baseline`. The earlier procedures did not record a historical candidate-approval digest. Never call this digest pre-interruption or infer that approval bytes were unchanged. |
| `RECOVERY_EXPECTED_SNAPSHOTS`, `RECOVERY_EXPECTED_DEPTH`, `RECOVERY_EXPECTED_TRADES`, `RECOVERY_EXPECTED_TOTAL` | Separately supplied operator-reported collector totals, respectively `1`, `35936`, `222238`, `258175`. The script pins this tuple and rejects absent or different input; the helper checks total arithmetic and exact agreement with the existing raw session **before** audit/replay. |
| `RECOVERY_EXPECTED_HOST` | Independently confirmed hostname matching both approvals. |
| `RECOVERY_AGENT_NAME_FILTER` | Operator-reviewed filter covering existing and replacement agent containers for mount isolation. |

Do not guess or reuse a mutable branch, agent checkout, changed image or
replacement config. The procedure fails closed unless the approved candidate
checkout still has full commit `91cd925d90bcc0f07d57b064dd180bc945c4602c`,
the recorded image ID is present, the active API ID/image and volume identity
match the original evidence, the guard accepts both paper-only approvals,
config hash manifests still pass, no other collector/volume writer is running,
and new/original evidence is isolated from agent mounts. It creates **one new**
private recovery evidence directory only after these read-only preflights.
No original evidence file is overwritten. It checks the original flat evidence
file set and hashes before and after the diagnostics. A new private baseline
record labels the candidate approval digest **current and operator-approved**,
with `historical_approval_unchanged_verified=false`; the count-comparison
record labels the totals **operator-reported, not directly host-inspected**.

After separate approval, an operator would invoke the staged script with
`bash` and the reviewed exports in scope; **that invocation is not part of
this PR**. The only Docker runs inside it are three newly named **read-only**
network-disabled, capped audit/replay containers against the existing image and
volume, without `--rm`. They remain stopped for inspection. On failure, only a
newly created, identity-verified diagnostic container may be stopped; it is
never removed. Neither an existing capture/container nor the active API is
stopped. Each run has a 3,600-second outer wall budget, 768 MiB/0.75 CPU/64
PID limits, and replay has a 3,300-second internal budget. The helper caps
ordered appended records at 2,000,000, raw files at 64, raw hash reads at
8 GiB per file, and metadata JSON at 4 MiB. Checks are cooperative and a
host operator must inspect any inconclusive cleanup before retrying.

## Interpretation and remaining gates

The independent stop reason, container exit/OOM status, duration, gaps/reconnects
and all original evidence still need direct private
operator inspection. A matching audit and two replays would show only stored
session consistency, not complete duration, exchange completeness, economic
acceptance, or a safe deployment. **Resource sampling is incomplete**, so even
matching operator-reported counts, audit and two replays cannot yield a full
soak pass. A missing original stop record also prevents such a claim. Retain
the new and original private evidence,
including raw hashes, recorded IDs/counts, audit and replay JSON and operator
inspection notes. Never publish private host paths, configs, logs or data in
this PR.

Local verification is synthetic only: Bash syntax, Python syntax, targeted
recovery regressions and full pytest. There was no VPS command or real-data
audit/replay in this PR.
