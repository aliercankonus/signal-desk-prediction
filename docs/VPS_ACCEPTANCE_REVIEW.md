# Draft VPS acceptance procedure for reviewed commit

**Review only. Do not run from the agent container or through the restricted SSH
gateway.** The proposed root-terminal script is
[`scripts/review/vps-acceptance-91cd925.sh`](../scripts/review/vps-acceptance-91cd925.sh).
It pins commit `91cd925d90bcc0f07d57b064dd180bc945c4602c`. This PR does not
approve, install, deploy or promote it. A manager and VPS root operator must
review the script and separately authorize any host execution. Stage the exact
reviewed bytes in a protected root-only location outside agent mounts; do not
execute a script from a writable development checkout.

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
Compose syntax, config/schemas and the entire pytest suite (**140 expected,
not a reported result**); requires an idle collector before a single bounded
1,000-event stream; records its fresh session ID and snapshot/depth/trade counts;
audits and replays that stopped session twice; compares every captured feature
hash and both `feature_sha256` results; hashes raw inputs before and after;
records sampled container stats, limits, disk and memory snapshots; and verifies
the old API/image, active settings/config and volume identity still match.

Every failure stops without promotion or retry. A failed live capture is stopped
by exact container ID, but partial root-owned approval files and the stopped
capture container are intentionally retained for inspection. A fast capture
without a live resource sample fails acceptance rather than inventing a metric.
Sampled Docker stats are **not** peak/p99 evidence, and a bounded parity result
is not 24-hour collection, restore, model or economic acceptance. No release
promotion procedure is proposed here.

Local review checks: `bash -n` on the script, compilation of its embedded
Python blocks, a secret/literal scan, and a diff restricted to this script and
document. No VPS acceptance command was executed for this PR.
