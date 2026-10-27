# Decision: portable one-command installer and versioned command catalog

## Status
Implementation candidate, 2026-10-27. Main merge and real installer acceptance pending.

## User requirement
Keep all setup/validation commands in the repository and repeat installation in one
operation. Use generic paths/parameters rather than publishing actual host identities.
Earlier main merge rejection was automatic approval review, not missing GitHub access.
This candidate is based on PR #3's already tested audit source; one approved merge
would include that feature too. No ref-update workaround is used to bypass approval.

## Sources checked
Official Docker documentation inspected 2026-10-27:
- https://docs.docker.com/engine/install/ubuntu/ — signed apt repository, package
  selection, prerequisite/conflicting runtimes and Docker service setup.
- https://docs.docker.com/reference/cli/docker/compose/up/ — --wait and --wait-timeout.
- https://docs.docker.com/compose/how-tos/startup-order/ — health vs running.
- https://docs.docker.com/build/concepts/context/ — build context and .dockerignore.
The code uses argv arrays, scoped Git safe.directory and no eval/global exception.

## Decision
Add install.sh for standalone clone/reuse/prerequisites, deploy.sh for local stages,
and install_check.py for strict paper-only API checks plus deployment manifest.
Keep existing active config and persistent volume; start API only. Short public
snapshot/25-record smoke is default, not an hour-long acceptance test every install.
Ubuntu 22.04/24.04 root setup of missing Docker is explicit --install-docker.
Do not reinstall a working engine, uninstall conflicts, force-checkout code, prune
volumes, alter other workloads or treat a container as a host.
Require host context, daemon/Compose/Buildx, no active project collector and basic
bootstrap capacity before changing deployment. Existing code changes cause a halt.
Retain tests before service up and --wait + paper/symbol/execution checks after it.
Keep local command log, commit/config hash, exact image IDs and dependency versions.
Publish INSTALLATION.md, docs/COMMANDS.md and sanitized technical PROJECT_STATE.
Keep full actual-host transcripts private. Runtime/.env/active config are excluded
from Docker context. New API binding defaults to loopback; explicit external bind
is a deployment choice, not TLS/auth implementation.

## Alternatives and risks
Manual multi-step setup remains in the catalog for diagnosis, not the default path.
A downloaded script is fully fetched before running; no curl-pipe partial execution.
A short install is not full restore, replay parity, production readiness or 24h soak.
Build/base image and OS package tags are not fully locked; manifest records actual
resolved values. Code can be pinned with --ref full SHA. Real clean-host execution
has not been demonstrated. API health failure does not auto-rollback an image.
10 GiB free / 1.5 GiB MemTotal are bootstrap floors, not retention capacity proof.

## Validation
88 local tests passed, shell syntax and config/schema checks passed. New tests fake
Docker/Git/host detection rather than installing host packages in the test environment.
They cover repeat preservation, custom port/project, failure gates before API,
host/daemon/collector blocks, health scope, explicit offline mode, no engine reinstall
and local manifest content. Actual Compose render/deploy, apt installation and
independent clean-host/restore tests remain pending.

## Rollback
Do not execute/merge the installer candidate until reviewed. Source rollback leaves
raw volumes untouched. Existing runtime rollback is manual using recorded image
identity/config; database/data restore is outside this candidate.


## Follow-up — 2026-10-27

The user explicitly approved the merge. PR #4 merged to main at
da3729f4bc86ff8f09283b1a190eecc6a37d7eba, including PR #3's raw audit source.
The user then supplied an existing-VPS DEPLOY_OK result, strict paper-only API
health, collector=idle, smoke=1 and local manifest/log paths. This is target-host
installation evidence, not independent clean-host/restore acceptance. Earlier
pending statements above describe the candidate at decision time.
