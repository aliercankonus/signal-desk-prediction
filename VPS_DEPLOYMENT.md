# VPS deployment runbook

Canonical installation: [INSTALLATION.md](INSTALLATION.md).
Full manual command catalog: [docs/COMMANDS.md](docs/COMMANDS.md).
Restricted gateway operations: [docs/OPERATIONS_RUNBOOK.md](docs/OPERATIONS_RUNBOOK.md).
Fail-closed diagnostics: [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## Existing checkout

```bash
bash scripts/install.sh
```

Outside the repository, use the script's absolute path or select the checkout with
--dir. Run on a Docker host; do not assume an agent container has host access.
Existing config/.env and the volume are preserved. The script does not reset Git,
prune or delete data. Select --ref explicitly for an update; Git conflicts are not
force-resolved.

## Scope

Build → config/schema → pytest → REST snapshot → short WS stream → API --wait/health
→ local manifest. Selecting --no-smoke does not establish feed acceptance.
Only the API starts; maintenance/collector services are not enabled automatically.
A new installation binds the API to loopback; external binding requires an explicit
--bind choice.

## Acceptance and records

DEPLOY_OK and runtime/install/run.*/manifest.json are produced only after all stages
pass. Previous image identity and command logs remain local. Installation success
is not proof of 24h collection, paper trading, p99 latency, data restore or strategy
success. Existing backup/restore/migration scripts are skeletons; do not assume
verified restore or disk expansion. Data migration needs separate acceptance.
