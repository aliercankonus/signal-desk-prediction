# Dated operations ledger (public, sanitized)

This ledger separates **directly observed command output** from
**operator/user reports**. It does not contain SSH endpoints, hostnames, private
keys, host-public-key material, private configuration, container IDs, manifest
paths or full host command logs. The private operator record is the source for
those details. A report of root-terminal action is not an independent audit of
host ownership, sshd policy or the protected release manifest.

| UTC date | Event | Provenance and observed result | Limit |
|---|---|---|---|
| 2026-10-27 | Dedicated account/key and initial hostname-only forced command | User supplied the proposed root-terminal setup; execution details were not directly witnessed by the agent. A later authenticated hostname-only SSH invocation was directly observed to exit `0`. | The diagnostic proved restricted SSH connectivity, not authorization for validation or deployment. Host-wide SSH policy and account ownership were not independently audited. |
| 2026-10-28 | Protected release approval and gateway activation | The installed gateway was reported to be available. The agent did **not** run or inspect the root-terminal approval/activation transaction. | Root-only manifest contents, mount isolation and sudoers/sshd policy were not independently read; subsequent gateway responses are evidence that the installed path functioned. |
| 2026-10-28 | Gateway `status` | Direct authenticated SSH output, exit `0`: project API healthy and bound to loopback. | Service health does not establish release identity beyond the gateway's own verifier, data continuity or strategy readiness. |
| 2026-10-28 | Gateway `validate` | Direct authenticated SSH output, exit `0`: collector image built, `schemas_ok=14`, `mode=paper`, full pytest **103 passed in 39.52s**. | No deploy was run as part of this validation operation. |
| 2026-10-28 | Gateway `deploy` and read-back | Direct authenticated SSH output, exit `0`: **DEPLOY_OK**, full pytest **103 passed in 38.31s**, snapshot `ok`, bounded stream **25 events** with `gap_count=0`, paper-only API health `ok`, `execution_enabled=false`, `ready_for_enter=false`, collector idle. A subsequent read-only `status` exited `0` and showed the API healthy. | The command printed private manifest/log paths, but their contents and exact image IDs were not independently read. This is not 24-hour, replay-parity, restore or economic acceptance. |
| 2026-10-28 | Development Git metadata repair | A fetch first failed because `.git/FETCH_HEAD` was `root:root` (`0:0`), mode `0644`. The operator reported correcting ownership. Later `stat` directly showed UID/GID **10000:10000**, mode `0644`, matching the development account, and `git fetch origin` succeeded. | The exact repair command was not witnessed. These numeric IDs are evidence for this checkout only, not an installation default; no protected release ownership was changed by the agent. |
| 2026-10-28 | Dirty-checkout preservation and private backup | Direct local checks: the original branch/worktree stayed dirty with its active config intact; a separate documentation worktree was created from main. A private restrictive backup copied and byte-compared all **10** inventoried changed/untracked files, stored a binary Git diff/status/HEAD/branch, and verified a **14-entry** SHA-256 manifest. | The backup is not a verified restore test; its private location and contents are intentionally absent here. |
| 2026-10-28 | Bounded candidate acceptance | **Operator-provided output**, not an agent-run command: `ACCEPTANCE_OK`, `RAW_INVENTORY_OK`, `RAW_VERIFY_PREFIX_OK`, `RAW_CHECK_CAPTURE_OK`, `RAW_CHECK_REPLAYS_OK`. The operator reported no API deployment or gateway promotion. | The supplied private evidence location was not accessed. No exact counts, test totals, feature hashes, resource measurements or host read-back were independently inspected. |

The reported run tested candidate `91cd925d90bcc0f07d57b064dd180bc945c4602c`
using the procedure merged through PR #9 at
`d5bba53fc6709af43b3821691a273e9a4622a119`. The operator says the active
gateway release remains `2d10f033faf7ecbf9064a957f2bacc91a979c1a8`;
the candidate was **not** promoted. The reported gate scope covers a bounded
capture, preservation of the original prefixes of historical raw files (while
allowing appends/new files), a session-scoped raw audit and two matching
replays. Longer collection, retention/restore, latency percentiles and model
performance are still unverified. The private evidence path and logs are kept
outside Git.

For future entries, record the **UTC date**, exact operation, actor, provenance
(direct observation vs report), exit code, bounded evidence and limitations.
Keep secrets, infrastructure identities, raw transcripts and local manifest
paths in the private operator log. See [OPERATIONS_RUNBOOK.md](OPERATIONS_RUNBOOK.md)
for the ordered procedure and [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for
fail-closed diagnosis.
