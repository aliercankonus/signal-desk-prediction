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
- Independent clean-host installation and restore remain pending.

## Completed vs pending
| Area | State |
|---|---|
| Paper-only API and bounded market-data collection | Implemented; bounded target-host evidence |
| Session-aware raw consistency audit | Implemented and target-host evidence |
| One-command installer and full generic command catalog | Implemented; existing-VPS DEPLOY_OK reported; independent clean host pending |
| Collector retention/compression | Quota/HALT guards only; automatic TTL/archive pending |
| Live/replay parity and bounded combined replay | Pending; old replay reads full JSONL lists |
| Backup/restore and second-host data migration | Pending; old scripts remain skeleton |
| Full paper ledger, EOD PnL and model economics | Pending |
| Time Machine | Specification only |
| Real orders | Out of scope, disabled |

## Next task

A hostname-only authenticated SSH check succeeded from the agent container; it
does not authorize deployment. PR #6 prepares a protected-release gateway design:
the VPS root operator must separately clone a reviewed full commit SHA outside
Hermes mounts, approve root-only config and manifest, then activate SSH. No host
setup, validation or deployment has been performed by this PR. The writable
development checkout is not the privileged deployment checkout and is not
re-owned. Independent clean-host installation and restore remain pending; build
bounded combined depth/trade replay before claiming live/replay parity. The
collector remains idle by default; live execution stays disabled.

## Records and ownership
- INSTALLATION.md: canonical repeatable install procedure.
- docs/COMMANDS.md: all generic manual setup, diagnosis and acceptance commands.
- decision_log: source research and rationale.
- runtime/install: private per-install command/output/image/config evidence, ignored
  by Git and Docker build context.
- Full actual-host command transcript stays in the user's private installation log.

## Repository language

All project documentation, skills, decision records, comments and user-facing
runtime messages are maintained in English, independently of conversation language.
