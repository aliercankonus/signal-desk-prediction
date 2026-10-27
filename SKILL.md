# signal-desk-prediction

## Purpose

Technical skill for a portable paper-only short-term prediction, decision, risk,
paper execution and EOD system, starting with Binance BTCUSDT spot market data.

This skill is not a running trading bot. Real orders, real money and trading API
keys are outside its scope.

## Repository language

Write all repository documentation, skills, decision logs, code comments and
user-facing runtime messages in English. The user's conversation language does not
change the repository language. Keep identifiers, paths, commands, numeric limits
and safety/acceptance semantics intact during translation.

## V0 decision

- Exchange: Binance.
- Product: BTCUSDT spot.
- Mode: paper-only.
- Execution: disabled.
- Scope: build all system components; do not require every strategy to succeed simultaneously.
- Runtime dependencies: no Ruflo/ECC; adapt selected methods only.

## Primary references

1. `references/01-scope-and-mvp.md`
2. `references/02-binance-market-data-adapter.md`
3. `references/03-data-contract.md`
4. `references/04-config-contract.md`
5. `references/05-resource-retention-and-200gb-migration.md`
6. `references/06-strategy-catalog.md`
7. `references/07-model-comparison.md`
8. `references/08-risk-decision-engine.md`
9. `references/09-paper-fill-model.md`
10. `references/10-eod-report.md`
11. `references/11-observability-and-alarms.md`
12. `references/12-portable-deployment.md`
13. `references/13-external-methods.md`
14. `references/14-acceptance-gates.md`
15. `references/15-research-decision-policy.md`
16. [Time Machine](references/16-timemachine.md): scenario and historical-rule research, separate from replay.

## Development sequence

1. Config + schema validation.
2. Docker skeleton + health endpoint.
3. Binance BTCUSDT sample feed → raw event.
4. Local order book bootstrap/gap/resync.
5. Feature snapshot + causality checks.
6. Baseline prediction + S1 strategy signal.
7. Risk/Decision Engine + paper-fill modes.
8. EOD + alarms.
9. Clean-host deployment and restore test.
10. Model comparison + forward paper test.

## Reporting rules

- If installation has not happened, report a design update rather than a running system.
- Make no profitability claim without project test evidence.
- Record each new technical decision with researched sources and a `decision_log` entry.
- Binance BTCUSDT is V0; futures/perpetual products require a separate V1+ experiment.

## Time Machine feature decision — 2026-10-27

Develop `timemachine` separately from replay. Keep Monte Carlo scenarios separate
from real historical-rule tests. Apply BTCUSDT spot paper-only, UTC, causality and
cost contracts. Read the [Time Machine contract](references/16-timemachine.md).
Only the feature design is accepted; the simulator, schemas and tests are not
implemented. VPS smoke tests do not depend on this feature.

## Continuous collector

For continuous collection, reconnect or resync, apply the
[collector contract](references/17-continuous-collector.md). Consult PROJECT_STATE.md
for later target-host evidence; historical candidate notes are not the current
checkpoint. Compose defaults to idle. Test the collector image first, then a bounded
60-second run. Do not deploy unattended 24/7 collection without successful validation
and resource measurements. Preserve Time Machine and real-order scope boundaries.

## Raw-data acceptance before replay

Apply the [raw-session audit contract](references/18-data-audit.md) to a completed
collector session selected by session_id. Check counts, schemas, sequence and file
hashes. The tool must not alter raw files. Do not substitute the old replay reader,
which loads entire large files into lists. A passing audit is not live/replay parity.

## Controlled host-command gateway

For a containerized agent, follow [INSTALLATION.md](INSTALLATION.md) to prepare
root-owned host-side forced-command and sudoers files in a separate VPS root
terminal. The only operations are status, validate and deploy, with no additional
arguments. The hostname-only SSH authorization remains unchanged until that
one-time host setup. Never treat command filtering as a sandbox: validation and
deployment run repository code with host privileges. Preserve the existing Compose
project, active config and volume; keep paper mode and execution disabled.

## Portable installation in one operation

Follow [INSTALLATION.md](INSTALLATION.md) and the [command catalog](docs/COMMANDS.md).
install.sh reuses an existing checkout or clones into a selected empty destination;
deploy.sh stops on a failed stage. Preserve active config/data and unrelated services.
Keep installation logs/manifests locally under runtime/install. Local mocked tests
are not clean-host, restore or paper-ready acceptance. If automatic review requires
explicit approval for a main merge, obtain it for the concrete PR; never bypass a
rejection by updating main through a ref mutation.
