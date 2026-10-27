# Restricted host-command gateway — 2026-10-27

## Decision

Prepare a dedicated SSH forced command accepting only exact `status`, `validate`
and `deploy` strings. Install the dispatcher, root wrapper, root-only configuration
and exact sudoers commands from a VPS root terminal, not through the existing
hostname-only SSH authorization. Retain the existing Compose project and active
paper-only configuration. The installer fails rather than replacing other active
SSH keys, creating a new project, or enabling continuous collection.

`status` reports Compose state, `validate` builds the collector and runs
Compose/config/pytest checks, and `deploy` delegates to the existing guarded
deployment script. No arbitrary remote arguments, eval, Docker-group membership
or unrestricted sudo are used.
The dedicated SSH account's home/key must be root-owned, and its parent paths
non-writable by the account, so it cannot rewrite its own forced command. The
installer publishes the forced key before the sudoers rule and refuses existing
key options other than the known hostname-only or already-installed gateway
restriction; it never silently drops a `from=` constraint. The operator pins
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
