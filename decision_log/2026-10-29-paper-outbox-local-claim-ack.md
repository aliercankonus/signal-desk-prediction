# Decision: fenced local-paper claim, receipt and acceptance ACK

## Boundary

This is an in-process, single-host SQLite paper receiver, not an exchange or network sender. BTCUSDT buy intent remains the original stable identity; an acceptance receipt and ACK mean **accepted locally, not filled**. Cash/risk reservations are neither released nor converted into positions. Fixture amounts, prices and fee buffers in tests are synthetic, not measured market costs.

## Atomic protocol

`PaperLedger.claim_outbox` holds `BEGIN IMMEDIATE` while checking the explicit writer ID/epoch, one committed intent, persisted receipt absence, caller-supplied UTC `claimed_at`, claim ID and per-intent claim version. SQLite permits one writer at a time, so competing claims cannot both commit against the same version.[1] The claim and hash-chained `outbox_claimed` event commit together. A claim has a 30-second caller-time lease and at most four lifetime versions per intent; no unresolved record is deleted. An identical claim/version is a no-op; a conflicting version or reused claim ID fails visibly. A takeover increments the persisted writer epoch and invalidates earlier claims even before their lease expires.

`LocalPaperReceiver` opens its **own** connection and rechecks the persisted writer fence, most recent claim version, exact claimed envelope/intent payload, deadline and existing receipt within its own serialized transaction **at acceptance**, not merely when the outbox was read. It atomically stores one immutable local receipt plus a `local_accepted` ledger event. Repeating the same delivery returns that receipt, even if the retry's observation time differs; a changed payload or claim identity fails. The receiver exposes no exchange/network operation. An expired lease prohibits *new* acceptance but does not prove a previous attempt failed: a retry checks the durable local receipt under the same database lock before claiming another version. This reasoning applies only to this co-located local receiver; an external sender would need a different protocol.

`ack_receipt` persists an immutable `outbox_acked` event linked to the receipt. A new writer can read the existing receipt after restart and ACK it without inventing an intent or resending. New risk is blocked while a local receipt remains unACKed; identical original-intent replay remains a no-op. ACK does not imply a fill. An ACK retry for the same receipt returns the original record. All operations retain the original cash/risk reservation and caller-supplied UTC event times, not wall-clock guesses.

## Recovery, bounds and migration

Schema v2 extends the append-only ledger with claim, receipt and ACK events and three immutable tables. Recovery pins one WAL snapshot and cross-checks the hash chain, event ordering, table counts, identities, envelopes, receipt/ACK links, triggers and unchanged budget totals. WAL readers keep a consistent snapshot while another connection commits.[1][2] Existing v1 files are **not silently upgraded**: normal `open` fails with a migration instruction. `PaperLedger.migrate_v1(path)` first verifies the v1 chain/budgets/triggers, then adds only the new empty tables/triggers and updates the schema version in one SQLite transaction; it leaves existing intents, reservations, outbox and ledger rows intact. It rejects a second migration or an unverified v1 file. Operators should make and verify a separate protected backup before any real migration; no host database was touched here.

Bounds: 2,048 intents; four claims per intent; one receipt and ACK each; at most 16,384 ledger events; 4,096 bytes per ledger/claim record; existing 64 MiB database, 4 MiB WAL and 1 MiB shared-memory admission checks. These are not a hard whole-filesystem quota. Existing `synchronous=FULL` WAL durability remains subject to host/filesystem/hardware sync behavior; synthetic process-crash tests are not a physical power-loss proof.[2][3] Any write or uncertain rollback halts the object until close, reopen, verification and writer takeover. An expiring claim never releases risk or deletes an unresolved record.

## Remaining boundaries

No fill, partial-fill, cancel/expiry transition, fee/slippage/PnL, risk latch, live wiring, network sender, externally verifiable lease clock, backup/restore acceptance or physical power-loss test is implemented. A future sender must not treat a returned claim as an ownership lease across arbitrary external actions; it needs separately reviewed receiver-side fencing and reconciliation. Strategy selection and real-data economic claims are out of scope.

## Sources

[1] https://www.sqlite.org/lang_transaction.html
[2] https://www.sqlite.org/wal.html
[3] https://www.sqlite.org/pragma.html
