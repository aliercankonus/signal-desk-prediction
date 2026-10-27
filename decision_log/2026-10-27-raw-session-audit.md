# Decision: audit captured sessions before full replay

## Status
Accepted implementation candidate, 2026-10-27. Real data acceptance pending.

## Context
Day-level raw files contain multiple trials. A successful bounded collector run
must be identified by session rather than assuming all rows belong to that run.
The existing replay reader loads JSONL into a list; do not run a large raw file
through it before building a bounded replay path.

## Sources checked
- Current project collector and schema at main 880ed1c8cedca4321087c1b252d529c74f318cbc:
  per-event data_quality.collector_session_id, per-stream raw files and previous IDs.
- Official Binance local-book sequence rules previously inspected 2026-10-27:
  https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md#how-to-manage-a-local-order-book-correctly
- Python incremental hashing API, inspected 2026-10-27:
  https://docs.python.org/3.12/library/hashlib.html
- Project schema validator reuse is unchanged; instance validation remains enabled.

## Decision and rationale
Add a read-only streaming audit tool with record-size and diagnostic bounds.
Filter the target session, compare persisted snapshot/depth/trade counts and depth
continuity with its run summary, and report whole-file digests. Check input identity
before/after scanning. Keep expected counts/session identity as CLI inputs, not
private deployment defaults embedded in source. Avoid unbounded duplicate-ID sets;
use per-stream sequence checks. Trade ID gaps are not proof of dropped trades.

4 MiB record cap is a project engineering bound above the 2 MiB REST helper response
cap plus normalized-event metadata. It is not a Binance requirement.
JSON syntax is checked globally; selected-session schema/semantics are checked
without treating historical unrelated schema versions as this session's contract.

## Tests and acceptance
67 local tests and config/schema validation pass. Target-host rebuild/tests and
actual selected-session audit are pending. A stored-consistency pass is not
live/replay feature parity, exchange completeness, zero loss, or economic acceptance.

## Alternatives
Full-file list loading, copying raw data into the assistant environment, modifying
raw files, and auditing all trials as one continuous book were not selected.

## Rollback
Remove/stop invoking the audit tool; no schema/config/raw migration required.
Keep the original files untouched.
