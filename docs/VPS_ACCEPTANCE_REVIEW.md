# Draft VPS acceptance procedure for reviewed commit

**Review only. Do not run from the agent container or through the restricted SSH
gateway.** The proposed root-terminal script is
[`scripts/review/vps-acceptance-91cd925.sh`](../scripts/review/vps-acceptance-91cd925.sh).
It pins commit `91cd925d90bcc0f07d57b064dd180bc945c4602c`. This PR does not
approve, install, deploy or promote it. A manager and VPS root operator must
review the script **and** [`scripts/review/acceptance_gates.py`](../scripts/review/acceptance_gates.py)
helper and separately authorize any host execution. Stage both exact reviewed
bytes together in a protected root-only directory outside agent mounts, verify
them against this PR's commit, and do not execute from a writable development
checkout. The helper runs on the VPS host from that staging directory; it is
**not** expected to exist in the pinned `91cd925…` candidate checkout.

## Inputs supplied privately by the root operator

The script has no embedded host identity, container identity, private key or
configuration value. Set these **environment variables in the trusted root
terminal** and export them after verifying each value on that host. Do not
commit a populated `.env`, paste private values in a PR, or use shell tracing:

| Variable | Required value |
|---|---|
| `ACCEPT_REMOTE` | Trusted Git remote, matching the active protected checkout's `origin` URL. |
| `ACCEPT_GUARD` | Existing installed, root-owned release verifier path. |
| `ACCEPT_ACTIVE_SETTINGS` | Existing root-only active gateway settings JSON path; read-only input. |
| `ACCEPT_RELEASE_ROOT` | Root-owned protected release parent under `/srv`, outside every agent mount. The SHA is appended. |
| `ACCEPT_CONFIG_ROOT` | Root-only parent for a **new** candidate configuration staging directory. The SHA is appended. |
| `ACCEPT_SETTINGS_ROOT` | Root-owned approval-record parent under `/etc/signal-desk/releases`; `<SHA>.json` is appended. This is **not** the active gateway settings path. |
| `ACCEPT_EVIDENCE_ROOT` | Root-only private evidence parent outside agent mounts. |
| `ACCEPT_EXPECTED_HOST` | Independently verified VPS hostname; must equal the active verifier's host and `hostname`. |
| `ACCEPT_AGENT_NAME_FILTER` | Docker container-name filter broad enough to cover the pinned agent and replacements for mount preflight. |
| `ACCEPT_CONTAINER_PREFIX` | Unique lowercase prefix for the one bounded capture container. |
| `ACCEPT_IMAGE_REPO` | Unique lowercase candidate image repository name, distinct from the active project's collector tag. |

The existing verifier supplies the active release, Compose project, agent
container ID and approved configuration identity. The script compares these to
the operator's inputs; it does not select or replace the active release.
`/srv/*` and `/etc/signal-desk/releases/*` are requirements of the installed
release guard, not examples to bypass. Container paths such as `/data/raw` are
the application contract, not host-specific paths.

After separate approval, the operator's invocation would be:

```bash
# In a trusted VPS root terminal, after setting all ACCEPT_* variables privately:
bash /root/path/to/protected-reviewed/vps-acceptance-91cd925.sh
```

That command is **documentation**, not an authorization to run it. Do not rerun
`install-host-gateway.sh`, call gateway `deploy`, run `deploy.sh` or `compose up`,
modify the active settings, remove old release files, or delete the data volume.
The script creates a separate release checkout and approval record using the
existing installed verifier; builds a uniquely tagged candidate image; checks
Compose syntax, config/schemas and the pinned candidate's entire pytest suite
(**140 expected in commit `91cd925…`, not a reported VPS result**). Separately,
this review branch has 22 local acceptance-gate regressions; those tests are
**not** part of the pinned candidate image. The procedure requires an idle
collector before a single bounded 1,000-event stream. Before starting it, the
script inventories **every existing raw file** in a private
`raw-pre-capture.json` with byte size, SHA-256 and device/inode. After the
capture exits, `raw-post-capture-prefix.json` requires every original file
still to exist on its original inode, be no smaller, and retain the original byte prefix (SHA-256 over the original length);
appends and new files are allowed. A missing, replaced, shortened or modified
original fails closed. The captured session must be new and contain **positive
depth and trade counts**, plus one snapshot and exactly 1,000 records.

The script then audits and replays the stopped session twice from a read-only
data mount. Both replays must verify 1,000 capture hashes, match exact event
counts and input-file hashes, have **positive `ready_features` separately in
each run**, and produce identical `feature_sha256` values. A post-capture
whole-file SHA-256 manifest for all `*.jsonl` inputs must remain unchanged
through audit/replay (distinct from the append-permitting pre-capture check).
Private evidence also contains capture stats/limits, disk and memory snapshots,
and checks that the old API/image, active settings/config and volume identity
still match.

Every failure stops without promotion or retry. Candidate one-off containers
have `--memory 512m --cpus 0.75 --pids-limit 64`, no network, and finite
wall-clock budgets: validation 180 seconds, pytest 600 seconds, raw audit
300 seconds, and **each** replay 600 seconds. `timeout` first sends INT and
then kills its Docker CLI after another 20 seconds; on nonzero exit the script
makes bounded attempts to stop/remove only the named candidate one-off
container, then fails. If Docker is unresponsive, cleanup is **not guaranteed**;
the root operator must inspect and resolve that container before any retry.
The live capture separately has the same resource caps and a 600-second wait.
On capture failure, cleanup attempts a bounded stop by exact container ID and
post-failure prefix verification; an unresponsive daemon or incomplete check
requires operator inspection. Partial root-owned approval files and the stopped
capture container are intentionally retained for inspection. A fast capture without a live resource sample fails acceptance
rather than inventing a metric.
Sampled Docker stats are **not** peak/p99 evidence, and a bounded parity result
is not 24-hour collection, restore, model or economic acceptance. No release
promotion procedure is proposed here.

Local review checks: `bash -n` on the script, Python compilation,
`PYTHONPATH=src python -m pytest -q` (162 locally passing, including 22 new
review-branch tests), targeted `tests/deployment/test_acceptance_review.py` gates, a secret/deployment-literal
scan, and a diff restricted to this script, helper, tests and document. These
are local review checks only. **No VPS acceptance or deployment command was
executed** for this PR.
