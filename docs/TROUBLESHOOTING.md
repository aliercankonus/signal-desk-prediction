# Troubleshooting and safe recovery

Use this guide for the writable **development checkout** and the restricted VPS
SSH gateway. Do not apply Git metadata fixes to the root-owned protected release
checkout, change its approved commit/configuration, or bypass a failed release
guard. The gateway is limited to `status`, `validate`, `deploy`; it is not a
root shell. Host-side repairs require an authorized operator at a separate VPS
root terminal. Keep secrets and host-specific identities out of public reports.

## Git fetch: `.git/FETCH_HEAD: Permission denied`

A writable worktree does not prove its Git metadata is writable. A previous
fetch in the development checkout failed because `.git/FETCH_HEAD` was owned by
`root:root` with mode `0644`, while the checkout was used by a non-root account.
The fetch stopped; local modifications and untracked files were not changed.

1. In the affected **development** checkout, record branch, status and ownership
   without changing anything:

   ```bash
   git branch --show-current
   git status --short --branch
   stat -c '%U:%G %a %n' .git .git/FETCH_HEAD .git/objects .git/refs
   ```

2. If metadata ownership is wrong, ask the checkout owner or authorized host
   operator to repair only the mismatched Git metadata so it is writable by the
   intended development account. For the isolated `FETCH_HEAD` case, after
   verifying the target account and that the path is a regular file, the
   operator can use a targeted command such as:

   ```bash
   # VPS/root terminal only; substitute the verified development account/group.
   chown DEV_USER:DEV_GROUP /path/to/development-checkout/.git/FETCH_HEAD
   ```

   If other `.git` paths have mixed ownership, inventory them and review each
   before a targeted repair. **Do not recursively re-own the working tree**, run
   `chmod -R`, or change any path under `/srv/signal-desk-releases/`. Never use
   `sudo git` in the development checkout as a workaround; it can recreate the
   mixed-ownership problem.

3. Retry `git fetch origin`, then recheck `git status --short --branch`.
   Fetching is not a license to overwrite a dirty checkout. If switching or
   pulling conflicts, stop; do not reset, clean, force or silently stash local
   changes, especially `config/config.yaml`.
4. To work independently from a dirty checkout, first verify the target branch
   and path are unused, then add a separate worktree from `origin/main`:

   ```bash
   git show-ref --verify --quiet refs/heads/docs/complete-operations-runbook
   # Exit 1 means the branch is absent; stop if it exists or another error occurs.
   test ! -e /path/to/separate-docs-worktree
   git worktree add -b docs/complete-operations-runbook \
     /path/to/separate-docs-worktree origin/main
   git -C /path/to/separate-docs-worktree status --short --branch
   ```

   A worktree shares Git metadata but has its own working files. It does not
   solve a permission error in shared `.git` metadata; repair that first.

## SSH or gateway fails before an operation

- `Permission denied (publickey)`: check the selected dedicated key, account,
  pinned known-hosts file and `IdentitiesOnly=yes`; do not disable host-key
  verification or add a second unrestricted key.
- Host-key mismatch: stop and verify the new fingerprint independently with
  the operator. Never accept it automatically.
- Unknown operation or extra arguments: send only one exact verb. No shell,
  flags, ref updates or repository promotion are authorized over SSH.
- Release verification failure (commit, owner, ancestor, symlink, mount, config
  hash, project or data-volume identity): **stop**. The root operator must
  compare the approved manifest and protected paths in a trusted terminal;
  do not patch the manifest, re-own the protected checkout or select another
  commit via SSH. A clean working tree alone is insufficient.
- A failed status/validate/deploy is not proof that the API is down; record the
  SSH exit code and failure output before any separate read-only diagnosis.

## Build, test or deployment failure

- Docker daemon/socket unavailable in the agent container: that does not
  establish a VPS daemon failure. Use only the installed gateway or an authorized
  host terminal; do not install a second Docker daemon inside the agent.
- Config/schema or pytest failure: record the precise failed stage and test
  output; stop before deploy. The collector image needs Git for fixture-created
  commits. Pytest's default `/tmp` has a writable ancestor; release-guard
  fixtures use a protected test directory, while production checks remain strict.
- `DEPLOY_FAILED stage=...`: preserve the printed host-local `deploy.log` path
  and inspect it with operator authorization. No automatic retry, image rollback
  or volume recreation is promised. An incomplete run has no success manifest.
- Compose orphan warnings identify other containers but do not authorize their
  removal. Do not run `--remove-orphans`, `prune` or `down -v` as a quick fix.
- A healthy API or `DEPLOY_OK` does not establish continuous collection, full
  ledger/PnL, replay parity, 24-hour stability or clean-host restore. The default
  collector remains idle, and real execution stays disabled.

Use [OPERATIONS_RUNBOOK.md](OPERATIONS_RUNBOOK.md) for the ordered gateway
operations, [INSTALLATION.md](../INSTALLATION.md) for operator-only release
approval, and [COMMANDS.md](COMMANDS.md) for generic diagnostics. Do not paste
private `.env`, raw command logs, access keys or host identifiers into Git.
