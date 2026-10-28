# 19 — Ordered capture and bounded session replay

## Status and acceptance boundary

Implemented candidate. Capture and replay call the same causal feature transition.
Local tests exercise capture writes, split files, merged replay and fault cases.
A fresh target-host capture/replay and resource trial are still required. Existing
one-hour raw files were audited but lack application-order metadata: they cannot
establish exact feature parity and must not be silently sorted into a claimed match.
The old protected VPS release remains unchanged until explicit root approval.
No prediction model, paper ledger, strategy acceptance or Time Machine is added.

## Why receipt/venue timestamps are insufficient

The collector opens WS and buffers events before obtaining REST depth. A buffered
trade/depth event may have an earlier receipt timestamp than the snapshot, while
the snapshot is applied first. Sorting split raw files by receipt or venue time
would move previously unavailable book information across the cutoff. Clock ties
and corrections also cannot recover application order.

New captures retain the original exchange/receipt/monotonic fields and add these
`data_quality` fields at the single writer:

- `collector_session_id`: fresh session identity, also for once/stream smoke.
- `ordering_version=session-applied-v1`.
- `ingest_sequence`: contiguous from 1, shared across depth and trade files.
- `applied_ts`: local UTC application cutoff.
- `applied_monotonic_ns`: application time in the same process clock as receipt.
- `feature_version=features-v17-applied-l2-trade` and the effective `feature_policy`.
- `feature_sha256`: digest of the canonical capture-time feature snapshot.

Metadata is additive inside the existing open `data_quality` object; no schema
migration or rewrite of historical raw files is performed. A fresh snapshot
creates fresh feature state. Recovery uses the collector's already fresh session
ID; it never compares monotonic values across sessions/reboots.

## Shared transition

`features/causal.py` applies book and trade events in recorded application order.
It reuses FeatureState's Decimal-based basic features with a distinct version and
application-based asof_ts. Original exchange timestamps remain in the raw event.
Trade quantities are lifetime-until-session-reset totals, not real rolling windows.

Require a starting snapshot, advancing contiguous ingest order, advancing applied
monotonic time, nondecreasing applied UTC, valid depth continuity/previous IDs,
positive prices/trades, nonnegative depth quantities and consistent trade sides.
Reject stale/duplicate depth, repeated/reordered trades and crossed/locked books.
A snapshot is not sufficient for readiness: require a depth bridge, both sides of
the book, and fresh depth and trade receipts at the application cutoff. Readiness
here is feature data quality, never permission to ENTER; API ready_for_enter remains false.

The hard bound is 20,000 total observed bid+ask levels, 64-character price/quantity
strings and existing 4 MiB replay records. Exceeding the book cap fails closed;
there is no silent pruning of potentially relevant levels. These are engineering
bounds, not a measured latency or 2 GB acceptance claim. Capture now computes and
validates features before raw persistence, so measure its added overhead on the VPS.
Existing validation, fsync, raw quotas and recovery policies remain enabled.

## Reader, merge and output limits

`python -m signal_desk.replay.session` accepts a completed session from standard
Binance BTCUSDT day-level depth/trade JSONL files. It uses two one-record lookaheads,
one active file per stream, fixed counters, a bounded book and at most 64 file
identities/digests. It does not load a history-sized list or event-ID set.
Merge by ingest_sequence, never by exchange time. Reject missing, duplicate or
reversed sequences. Check captured feature version/policy and every feature hash.

Read at most 4 MiB+1 per line. Malformed JSON, duplicate JSON keys, nonstandard
constants and incomplete/oversized lines fail globally, including unrelated
sessions whose identity cannot reliably be established. Schema and feature
semantics are checked for the selected session. Reject symlink/nonregular inputs,
wrong stream placement, unrecognized JSONL filenames and inventory changes.
Report whole-file SHA-256 fingerprints, not venue authenticity proofs.

Default runtime budget is 600 seconds (maximum 3600); checks are cooperative at
record/transition boundaries, not a hard preemptive OS deadline. Default/hard
feature byte budget is 256 MiB, even in digest-only mode. Reject rather than return
a truncated successful replay. Output parents must already exist outside raw_dir.
If requested, stage one private temporary output, fsync it, and publish without
overwriting an existing destination, including a competing writer's destination.
Failure removes the temporary output. This is atomic publication, not a claim of
crash-proof disk durability or isolation from a malicious filesystem writer.

Require stopped collection; before/after identity checks detect ordinary concurrent
changes but do not freeze data or authenticate it. Supply independently recorded
snapshot/depth/trade totals to verify session completion. Without those totals,
`expected_counts_checked=false`: matching hashes alone cannot detect a removed
trailing prefix. Neither mode proves exchange completeness, zero loss or economics.

The old single-file runner now uses a record-bounded iterator rather than loading
all JSONL rows, but remains a legacy fixture tool without cross-file parity,
application-clock semantics, atomic output or the new book cap. Do not use it as
an alternative acceptance path for large historical production files.

## CLI and target-host acceptance

Run only from an operator-reviewed/approved release or isolated development image.
The existing SSH gateway intentionally cannot select new code or run arbitrary
replay commands; it still targets its previously approved release. Do not bypass
that release gate or modify the installed root wrappers to run this candidate.

After a new bounded stream capture has stopped, take session_id and exact totals
from its summary. The old one-hour session is expected to return unsupported.
Digest-only default does not write features, raw data, status or a ledger:

```bash
docker compose -p signal-desk-prediction run --rm --no-deps collector \
  python -u -m signal_desk.replay.session \
  --raw-dir /data/raw --session-id SESSION_ID \
  --expected-snapshots 1 --expected-depth DEPTH_COUNT --expected-trades TRADE_COUNT
```

Optional feature output (create the parent separately, outside raw_dir):

```bash
docker compose -p signal-desk-prediction run --rm --no-deps collector \
  python -u -m signal_desk.replay.session \
  --raw-dir /data/raw --session-id SESSION_ID \
  --output /data/features/UNIQUE_RUN_ID.jsonl \
  --expected-snapshots 1 --expected-depth DEPTH_COUNT --expected-trades TRADE_COUNT
```

Exit 0: all selected stored hashes/counts passed. Exit 2 with unsupported: legacy
ordering metadata is missing. Other exit-2 failures include input, ordering,
feature, count, resource and publication faults. No repair/deletion on failure.
Require repeated feature digests, exact event totals and no input changes. Measure
RAM/CPU/capture overhead before extending a trial. A passing bounded session is not
24h operation, p99 latency, clean-host restore, a trained model or profitable trading.
