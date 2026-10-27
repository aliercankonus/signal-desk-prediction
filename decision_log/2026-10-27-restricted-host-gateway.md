# Restricted host-command gateway — 2026-10-27

## Decision

Prepare a dedicated SSH forced command accepting only exact `status`, `validate`
and `deploy` strings. The VPS root operator first clones a reviewed full commit
SHA into a separate root-owned checkout outside Hermes mounts, stages approved
config outside the shared tree, independently verifies SHA/path/mount isolation
before running checkout code, and installs a root-owned verifier copy. It pins
the SHA, project, host, agent container, config hashes and identity of the
running API's existing data volume in a root-only manifest. The writable Hermes
development checkout is not re-owned or used to execute privileged deployment.
Only a second explicit root-terminal step installs the dispatcher, root wrapper
and exact sudoers commands, using the previously installed verifier. The
hostname-only key is unchanged by PR changes or by release preparation. SSH
has no fetch, checkout, selection or promotion operation.

`status` reports Compose state, `validate` builds the collector and runs
Compose/config/pytest checks, and `deploy` delegates to the existing guarded
deployment script. No arbitrary remote arguments, eval, Docker-group membership
or unrestricted sudo are used.
The dedicated SSH account's home/key must be root-owned, and its parent paths
non-writable by the account, so it cannot rewrite its own forced command. The
installer publishes the forced key before the sudoers rule, refuses an
existing or partial gateway activation, and requires the known hostname-only
key restriction; it never silently drops a `from=` constraint. The operator pins
the key's SHA-256 fingerprint against a trusted public key and refuses an
agent-writable checkout or critical input. Installation still requires the root
operator to review and trust the repository checkout; validation and
deployment execute repository code with Docker/host privileges, so command
filtering is not a security sandbox.
Host address, checkout path, account, key location and project are deployment
settings, not committed identities or secrets.

## Sources and rationale

- OpenSSH `authorized_keys` supports per-key `command=` and `restrict` options;
  a forced command receives the requested text via `SSH_ORIGINAL_COMMAND`.
  https://man.openbsd.org/sshd#AUTHORIZED_KEYS_FILE_FORMAT
- `sudoers` supports exact command/argument matching and `NOPASSWD`; it does not
  make the allowed program safe against mutable inputs. Validate the drop-in with
  `visudo -c` before installation.
  https://www.sudo.ws/docs/man/sudoers.man/
- Docker daemon access is root-equivalent and must not be granted to the SSH
  agent directly. Compose project names scope resources, including volumes.
  https://docs.docker.com/engine/security/
  https://docs.docker.com/compose/how-tos/project-name/

## Limits

This is local preparation, not a VPS installation or clean-host test. Existing
host-wide SSH policy, pre-existing sudo rules, ownership of the repository and
backup/restore need separate host-side review. Root-side code changes must be
reinstalled after review; changing the repository file alone does not change the
installed root-owned wrappers.
