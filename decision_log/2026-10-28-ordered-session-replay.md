# Decision: capture application order before claiming merged feature parity

## Status
Implemented candidate, 2026-10-28; target-host capture/replay acceptance pending.

## Context and inspected sources

At main 2d10f033faf7ecbf9064a957f2bacc91a979c1a8, collector mapping occurs in the WS
receiver before REST completes, while snapshot persistence precedes buffered events.
Depth/trades are stored in separate day files without a global application counter.
The one-hour session audit proved selected stored consistency, not causal replay.
The old replay reader loaded entire JSONL files and had no split-stream merge.

Sources inspected 2026-10-28:
- Project collector, mapping, book, features, raw-session audit and market/feature schemas.
- Project data/EOD contract: session ingest order and local availability cutoff;
  never sort venue time to import later information into an earlier decision.
- Python binary IO readline(size): https://docs.python.org/3.12/library/io.html
- Python file/link APIs: https://docs.python.org/3.12/library/os.html
- Earlier reviewed Binance local-book procedure remains unchanged:
  https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md#how-to-manage-a-local-order-book-correctly

## Decision

Stamp a shared session sequence and local application cutoff at capture. Compute a
versioned feature hash with the same bounded transition used offline. Retain venue
and receipt clocks; do not rewrite historical events. Merge two bounded stream
heads by sequence and verify each hash. Missing legacy metadata is unsupported,
not a guessed historical parity result. Keep models/orders/Time Machine separate.
See references/19-ordered-session-replay.md for numeric engineering bounds, CLI,
readiness semantics and independent completion-count requirements.

## Alternatives and risks

Receipt/venue sorting, concatenated streams, full-history list loading and silently
pruning book levels were rejected. Capture feature computation adds CPU/validation
and raw metadata overhead; previous one-hour resource numbers do not validate it.
Fail closed on resource/clock/sequence violations. Shared-core hashes detect replay
or persistence divergence, not bugs common to both paths or exchange authenticity.
Additional known-value and future-data tests are required alongside parity tests.
File identity checks do not replace completed collection or a trusted snapshot.

## Validation and rollout

Tests cover known features, captured order across the REST buffer boundary,
future-prefix invariance, midnight files, session reset, gaps/duplicates, hash/policy
mismatches, clock errors, malformed input, mutation, limits, atomic no-overwrite
publication and record-count-independent memory. Actual results are recorded in the
PR/checkpoint. A fresh VPS capture, replay and overhead measurement remain mandatory.
No automatic update of the installed protected release or gateway occurs.

## Rollback

Keep the previous approved image/release; preserve raw data. New metadata is additive.
Older tools may ignore it, but must not claim the new feature parity. Reverting the
candidate does not restore missing order metadata to legacy sessions.
