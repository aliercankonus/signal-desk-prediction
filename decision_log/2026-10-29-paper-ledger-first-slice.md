# Decision: first shared paper intent ledger and reservation outbox

## Status and boundary

Proposed paper-only storage slice. No live wiring, exchange credentials, network sender, complete fill/exit engine, strategy selection, training, real-data PnL or deployment. The existing `DecisionEngine` and `fill_model` are skeletons; this slice consumes a caller-reviewed intent rather than pretending they implement a full risk or cost gate. Synthetic test prices, quantities, cash budgets and fee buffers are **fixtures**, not market prices or a validated fee policy.

## Storage and identity

Use a single local SQLite database in WAL mode with `synchronous=FULL`, `BEGIN IMMEDIATE`, foreign keys, a verified page size and bounded connections. SQLite documents that FULL in WAL mode syncs the WAL after each transaction commit to improve power-loss durability; NORMAL can lose the last committed transactions on a power failure.[1][2]

SQLite serializes write transactions; IMMEDIATE takes the writer slot before reading budgets, rather than attempting an unsafe read-to-write upgrade.[3] WAL must remain on one host-local filesystem, not a network filesystem.[2]

Each accepted BTCUSDT spot **buy-only** intent has a stable ID derived from strategy, signal, config and portfolio versions, feature snapshot ID, caller-supplied decision UTC time, side, BTC quantity and plan hash, consistent with `references/08-risk-decision-engine.md`. No wall clock enters the stored intent. Decimal strings are validated and normalized under a fixed precision independent of the caller's ambient Decimal context; `qty_btc × price_ceiling_usdt_per_btc + fee_buffer_usdt` gives the exact USDT cash reservation. The USDT risk reservation is independently supplied by the caller and must fit a declared paper budget. This is not a fee estimator, risk model or paper fill.

Under one transaction, verify explicit writer ID/epoch and portfolio version, check unreserved paper cash/risk, and insert the intent, reservation, **local-paper-only** pending outbox and two hash-chained ledger entries. An identical repeated ID/content is a no-op; the same ID with different content fails, as does a stale portfolio or writer. Ledger rows reject UPDATE/DELETE and unresolved intents/reservations/outbox rows reject DELETE. The writer claim advances a persisted epoch, fencing earlier claimants; exposing pending outbox **or audit ledger** payloads also requires the current fence under a serialized read. A returned payload is **not a delivery lease** after that read; any future sender must revalidate its fence and define a separate safe claim/ack protocol before delivery. A trusted operator still must control which process receives the current fence. No connector reads the outbox or sends an exchange request in this slice.

## Recovery and failure boundary

On restart, bound file/record reads, hold one consistent WAL read snapshot, verify required append-only triggers, chain and schemas, and compare reconstructed reservations, intent identities, outbox and portfolio totals with materialized tables. Recheck the required triggers within every serialized ledger transaction so a removed trigger halts new risk even after an object has opened. Pending outbox rows are visible only after commit. A write error blocks new risk on that object; if COMMIT reports uncertainty, reopen and reconcile before claiming a new writer epoch. Do not mint a replacement identity for an uncertain intent. The current slice has no cancel/fill/release transition, so reservations remain unresolved and must not be deleted to reclaim capacity.

Limits are 2,048 intents, 4,096 ledger entries, 4,096 bytes per record, 64 MiB database and 4 MiB WAL pre/post checks, a 1 MiB shared-memory check, 4 MiB SQLite cache and 64-page WAL autocheckpoint. `max_page_count` limits database growth; SQLite auxiliary files and other processes may temporarily consume additional space, so these are admission limits, **not a proven filesystem-wide hard quota**. Stop new risk on a bound or storage error rather than pruning unresolved rows. The repository's larger disk-profile budget and alarm policy remain separate.

Exception rollback, concurrent writers, subprocess termination before commit and process restart are tested using synthetic local data. Those are **crash/recovery tests, not proof of survival across physical power loss**, broken `fsync`, storage-controller caches, directory-entry persistence or host filesystem failure. SQLite's atomicity/durability description explicitly depends on filesystem and hardware sync assumptions.[4] A real durability claim requires a separately reviewed host/filesystem/power-loss test and backup/restore exercise; none is authorized here.

## Remaining paper-core work

Implement cost/freshness gates, risk latches, fill/partial-fill/cancel/expiry/reconciliation transitions, safe outbox consumption, fee/slippage policies, mark-to-market, EOD, snapshots/backups and live/replay integration under separate review. This ledger does not turn the development diagnostic into an untouched final test or establish economic acceptance.

## Sources

[1] https://www.sqlite.org/pragma.html
[2] https://www.sqlite.org/wal.html
[3] https://www.sqlite.org/lang_transaction.html
[4] https://sqlite.org/atomiccommit.html
