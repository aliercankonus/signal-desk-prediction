# Project State

Updated: 2026-10-28. This is the public technical checkpoint, with no host-specific
names, paths, container identities, credentials or full operational transcripts.
Repository: https://github.com/aliercankonus/signal-desk-prediction

## Scope
- Binance BTCUSDT spot, paper-only; execution_enabled=false.
- Default budget: 100GB disk / 2GB RAM. 200GB expansion remains a planned profile.
- S1 order-flow is the primary research candidate, not proven profitable.
- Compose collector default remains idle. API readiness is not an ENTER permission.

## Source and implementation
- Main installation/audit baseline: da3729f4bc86ff8f09283b1a190eecc6a37d7eba (PR #4 merged).
- Raw-session audit from PR #3 is included in main; both PRs are merged.
- Installer: standalone install.sh, existing/fresh checkout handling, optional
  fresh-Ubuntu Docker prerequisites, deploy gates and secret-free local manifest.
- Runtime image IDs/config hash/git commit are captured by each successful installer;
  no exact running image identity is fabricated in this public checkpoint.

## Evidence
- Before installer additions, 67 tests passed on the target host.
- Snapshot, 25/1,000-record and 60/300s collector trials passed.
- One-hour bounded collector: 186,898 persisted records, zero sequence gaps/reconnects,
  normal exit and no OOM. Resource snapshots were low; peaks/p99 not measured.
- Recovery trial: two reconnects, fresh synchronized session, failure counter reset,
  normal duration stop. Individual generic timeout causes remain not fully attributed.
- Real raw-session audit: 1 snapshot + 35,887 depth + 151,010 trades, no reported errors.
- Installer candidate: 88 local tests passed, including mocked Docker orchestration
  failure/preservation gates and real application checks. Shell syntax/config validated.
- Existing target-VPS installer run reported DEPLOY_OK on 2026-10-27: API health
  status=ok, mode=paper, execution_enabled=false, config=cfg-v16-example-001,
  collector=idle, smoke=1; local manifest and command log paths were reported.
- The assistant did not independently inspect that manifest or its exact image IDs.
- Ordered capture/replay acceptance for candidate
  `91cd925d90bcc0f07d57b064dd180bc945c4602c` was reported by the VPS
  operator on 2026-10-28, using the procedure merged in PR #9 at
  `d5bba53fc6709af43b3821691a273e9a4622a119`. The operator supplied
  `ACCEPTANCE_OK`, `RAW_INVENTORY_OK`, `RAW_VERIFY_PREFIX_OK`,
  `RAW_CHECK_CAPTURE_OK` and `RAW_CHECK_REPLAYS_OK`. This reports a bounded
  capture, preservation of historical raw-file prefixes, raw audit and two
  matching replays; the assistant did not access the private evidence or
  independently inspect counts, hashes or resource measurements.
- The operator reports no API deployment or gateway promotion. The active
  gateway release remains `2d10f033faf7ecbf9064a957f2bacc91a979c1a8`,
  distinct from the tested candidate. This is not a direct host read-back.
- Independent clean-host installation and restore remain pending.

## Completed vs pending
| Area | State |
|---|---|
| Paper-only API and bounded market-data collection | Implemented; bounded target-host evidence |
| Session-aware raw consistency audit | Implemented and target-host evidence |
| One-command installer and full generic command catalog | Implemented; existing-VPS DEPLOY_OK reported; independent clean host pending |
| Collector retention/compression | Quota/HALT guards only; automatic TTL/archive pending |
| Ordered capture and bounded combined replay | Candidate implemented; operator-reported bounded VPS acceptance, private evidence uninspected; longer soak pending |
| Backup/restore and second-host data migration | Pending; old scripts remain skeleton |
| Full paper ledger, EOD PnL and model economics | Pending |
| Time Machine | Specification only |
| Real orders | Out of scope, disabled |

## Next task

After separate operator review, propose **one** candidate-only 60-minute soak,
not an active-gateway deployment: confirm the existing API/release/volume and
paper-only settings, require no other collector, then start a uniquely named
collector with `--max-run-seconds 3600`, `--restart no`,
`--memory 512m --cpus 0.75 --pids-limit 64`, and a 3,900-second outer wall
budget. Stop only that candidate container on timeout or failure; do not retry
or switch the gateway automatically. Acceptance would require an exited/0,
non-OOM duration stop, positive depth and trade counts, zero gaps and zero
reconnects, preservation of every pre-existing raw-file prefix (appends/new
files allowed), a clean session-scoped raw audit, two matching bounded replays
with verified capture hashes and positive `ready_features`, and unchanged
active API/image/settings and volume identity. Retain root-only start/end
UTC times, container/image/limit/exit metadata, periodic Docker stats, status
and logs, exact counts/session ID, pre/post raw inventory and hashes, audit and
both replay results, and disk/memory snapshots. Sampled stats are not peak or
latency-percentile measurements. **This is a proposal, not an executed test.**
Longer collection (including 24 hours), retention/restore, latency percentiles
and model performance remain unverified; any release promotion needs separate
authorization.

## 2026-10-28 operational evidence and candidate

- PR #6 merged at 2d10f033faf7ecbf9064a957f2bacc91a979c1a8. Its CI passed all
  103 tests inside the collector image.
- Authenticated gateway `status`, `validate` and `deploy` were observed via SSH
  on the target host. Host validation passed 103 tests; deployment passed 103
  tests, snapshot and a 25-event stream with gap_count=0. The API was healthy
  on loopback, paper-only, execution disabled, ready_for_enter=false, collector
  idle. Host-local manifest/log paths were printed; their contents and exact
  image IDs were not independently read.
- Candidate `91cd925d90bcc0f07d57b064dd180bc945c4602c` adds session
  application sequence, application-clock features, capture-time feature hashes
  and bounded split-stream replay. The operator reports a bounded VPS
  acceptance run, **not** API rollout or gateway promotion of this candidate.
- New capture processing and metadata overhead still need longer-duration
  resource measurements. Earlier one-hour collector measurements are not
  evidence for this candidate.
- Clean-host restore, longer collection, retention, latency percentiles,
  model economics, full ledger/PnL and Time Machine implementation remain pending.

## Records and ownership
- INSTALLATION.md: canonical repeatable install procedure.
- docs/OPERATIONS_RUNBOOK.md: restricted gateway operation gates and private evidence.
- docs/OPERATIONS_LEDGER.md: dated public evidence, labelled by provenance and limits.
- docs/TROUBLESHOOTING.md: fail-closed diagnosis, including development Git metadata ownership.
- docs/COMMANDS.md: all generic manual setup, diagnosis and acceptance commands.
- decision_log: source research and rationale.
- runtime/install: private per-install command/output/image/config evidence, ignored
  by Git and Docker build context.
- Full actual-host command transcript stays in the user's private installation log.

## Repository language

All project documentation, skills, decision records, comments and user-facing
runtime messages are maintained in English, independently of conversation language.
