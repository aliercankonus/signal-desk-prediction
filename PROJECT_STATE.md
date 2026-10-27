# Project State

Updated: 2026-10-27. This is the public technical checkpoint, with no host-specific
names, paths, container identities, credentials or full operational transcripts.
Repository: https://github.com/aliercankonus/signal-desk-prediction

## Scope
- Binance BTCUSDT spot, paper-only; execution_enabled=false.
- Default budget: 100GB disk / 2GB RAM. 200GB expansion remains a planned profile.
- S1 order-flow is the primary research candidate, not proven profitable.
- Compose collector default remains idle. API readiness is not an ENTER permission.

## Source and implementation
- Main baseline: 880ed1c8cedca4321087c1b252d529c74f318cbc (continuous collector).
- Raw-session audit: PR #3 source 1bf9805fdb176e349eb47ac615d35b422b0db1e2;
  real-data acceptance passed, main merge was blocked pending explicit authorization.
- This installer candidate is based on that audit commit, so it includes the
  verified audit feature as well as one-command installation and command docs.
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
- Actual installer on target host and independent clean-host installation pending.

## Completed vs pending
| Area | State |
|---|---|
| Paper-only API and bounded market-data collection | Implemented; bounded target-host evidence |
| Session-aware raw consistency audit | Implemented and target-host evidence |
| One-command installer and full generic command catalog | Candidate implemented; host acceptance pending |
| Collector retention/compression | Quota/HALT guards only; automatic TTL/archive pending |
| Live/replay parity and bounded combined replay | Pending; old replay reads full JSONL lists |
| Backup/restore and second-host data migration | Pending; old scripts remain skeleton |
| Full paper ledger, EOD PnL and model economics | Pending |
| Time Machine | Specification only |
| Real orders | Out of scope, disabled |

## Next task
Review/test the installer candidate on a Docker host, inspect local install manifest,
then obtain explicit authorization for its exact main-branch merge.
One main merge of the installer candidate would also include PR #3's audit source.
No 24h service or live execution is enabled by creating/merging these source files.

## Records and ownership
- INSTALLATION.md: canonical repeatable install procedure.
- docs/COMMANDS.md: all generic manual setup, diagnosis and acceptance commands.
- decision_log: source research and rationale.
- runtime/install: private per-install command/output/image/config evidence, ignored
  by Git and Docker build context.
- Full actual-host command transcript stays in the user's private installation log.
