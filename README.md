# Signal Desk Prediction

A paper-only collector, research, replay and decision system starting with Binance
BTCUSDT spot. Real orders are disabled. A working collector does not establish a
profitable strategy or a complete paper ledger.

## Project language

Repository documentation, skills, decision records, code comments and user-facing
runtime messages must be written in English. Conversation language does not change
this requirement. Preserve identifiers, command syntax and contract semantics when
translating existing material.

## Install from an existing checkout

From the repository directory:

```bash
bash scripts/install.sh
```

The installer preserves configuration and the data volume. It runs image builds,
config/schema validation, the full test suite, a short public Binance smoke test
and API health checks in sequence. Only the API starts; the collector remains idle
by default. An existing Docker engine is not reinstalled.

## Install on a new server in one operation

Run from the Ubuntu 22.04/24.04 host terminal with root/sudo access:

```bash
sudo bash -c 'set -eu; command -v curl >/dev/null || { apt-get update; apt-get install -y ca-certificates curl; }; f=$(mktemp); trap "rm -f \"$f\"" EXIT; curl -fsSL https://raw.githubusercontent.com/aliercankonus/signal-desk-prediction/main/scripts/install.sh -o "$f"; bash "$f" --install-docker'
```

The default checkout is `/opt/signal-desk-prediction`; the API binds to
`127.0.0.1:8080`. Run from the VPS host terminal. Restoring historical data/models
and starting a continuous collector are separate steps.

Full options: [INSTALLATION.md](INSTALLATION.md).
Manual setup, diagnostics and test commands: [docs/COMMANDS.md](docs/COMMANDS.md).
Restricted gateway status/validate/deploy procedure: [docs/OPERATIONS_RUNBOOK.md](docs/OPERATIONS_RUNBOOK.md).
Dated, provenance-labelled operational evidence: [docs/OPERATIONS_LEDGER.md](docs/OPERATIONS_LEDGER.md).
Fail-closed diagnostics and Git metadata repair: [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).
Deployment entry point: [VPS_DEPLOYMENT.md](VPS_DEPLOYMENT.md).

## Commands and installation records

| Need | Repository source |
| --- | --- |
| New/existing server installation, options and failure behavior | [INSTALLATION.md](INSTALLATION.md) |
| Docker/host diagnostics, config, builds, tests, API, snapshot and stream | [docs/COMMANDS.md](docs/COMMANDS.md) |
| Resource, recovery, one-hour soak and raw-session audit commands | [docs/COMMANDS.md](docs/COMMANDS.md) |
| Restricted SSH operations, gates, evidence and limitations | [docs/OPERATIONS_RUNBOOK.md](docs/OPERATIONS_RUNBOOK.md) |
| Dated operational evidence with provenance and limitations | [docs/OPERATIONS_LEDGER.md](docs/OPERATIONS_LEDGER.md) |
| Fail-closed troubleshooting and development Git metadata permissions | [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) |
| Current technical status and remaining acceptance work | [PROJECT_STATE.md](PROJECT_STATE.md) |

Each installer run writes `deploy.log`, commit/config hashes and, on success,
`manifest.json` under `runtime/install/run.*/`. Reuse the same script for later
installations and retain the recorded versions. The manual catalog uses parameters
for host paths, hostnames and session IDs.

## Evidence and limitations

- Target-host collector tests covered snapshots, 25/1,000-record smoke tests,
  bounded continuous collection and recovery.
- One-hour run: 186,898 records, zero gaps/reconnects, normal exit and no OOM.
- Scoped raw audit: the same 186,898 records, no errors. This is not live/replay
  parity or proof of exchange completeness.
- Installer orchestration has local fake-Docker test coverage. The user-reported
  existing-VPS run returned `DEPLOY_OK`, with paper-only API health and local logs.
  Independent clean-host installation remains unverified.
- A 24h soak, p99 latency, target-host ordered replay parity, data restore, full ledger/PnL
  and economic model acceptance remain incomplete. Time Machine is specification-only.

The installer keeps command logs and version/hash manifests locally. Host-specific
identities and private paths are not published in source. `PROJECT_STATE.md` is the
technical checkpoint; `decision_log` records rationale; `runtime/install` stores
local installation evidence.


## Ordered capture/replay candidate

New capture code records application order and feature hashes. The bounded
[session replay tool](references/19-ordered-session-replay.md) merges depth/trades
by that order and checks every captured hash. Historical sessions lack this
metadata and cannot establish exact parity. Target-host acceptance is pending;
the currently approved VPS release is not updated by this source change.
