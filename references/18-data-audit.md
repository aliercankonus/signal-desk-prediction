# 18 — Read-only raw-session audit

## Status
Implemented locally; 67-test suite and config/schema validation pass.
Real captured-session audit on the target host is pending. This tool does not
change collector behavior, storage, active config or execution permissions.

## Purpose and scope
Audit one collector session within shared day-level depth/trade JSONL files.
Previous failed trials may exist in the same files: select data_quality.collector_session_id.
Parse JSON syntax for every physical line; validate schema and additional event
semantics only for the selected session. Report whole-file SHA-256 and byte counts.
The hash is a local fingerprint, not proof of Binance authenticity or completeness.

Check selected depth sequence, preceding snapshot, previous_final_update_id,
nonadvancing depth and duplicate/reordered trade IDs. Do not equate a gap between
trade IDs to missing market trades. Validate positive prices/nonnegative depth
quantities, positive trade size, trade-side mapping, aware ISO timestamps and hash shape.
Compare persisted event counts to the separately recorded collector summary.
No cross-file event merge, replay features, live/replay parity or profitability here.

## Bounded memory and immutability
Read binary JSONL with readline(limit+1), 4 MiB maximum record size. Drain oversized
records in bounded chunks while hashing their complete bytes. Keep only fixed
counters/sequence state, five diagnostic samples and per-file metadata.
Never load all records into a list or keep an unbounded event-ID set.
Do not use the old read_jsonl list reader for this audit.
Require completed collection. Detect input metadata/file-set changes during audit
and fail rather than reporting a changing dataset as an accepted artifact.
Do not run a collector concurrently. The tool reads raw files and prints JSON;
it does not write a manifest, temp file, feature file, ledger or modified raw data.

## CLI
Build/test the candidate image first. Then from the project directory:
```bash
docker compose -p signal-desk-prediction run --rm --no-deps collector \
  python -u -m signal_desk.tools.audit_raw \
  --raw-dir /data/raw --session-id SESSION_ID \
  --expected-snapshots SNAPSHOT_COUNT --expected-depth DEPTH_COUNT \
  --expected-trades TRADE_COUNT
echo "AUDIT_EXIT_CODE=$?"
```
Replace uppercase tokens with values from the recorded completed run.
Exit 0: scoped audit passed. Exit 2: input/count/sequence checks failed.
Exit 1: directory, permission, schema-loading or other operational failure.
A failed audit never deletes/repairs records. Inspect errors before any replay.
A syntactically damaged record outside the selected session also fails the scan:
its session cannot be established reliably.

## Limitations
Ordered per-stream files are processed by filename order. Current collector filenames
sort dates in stream order. No general merge of arbitrary filenames is implied.
Stat/identity checks detect ordinary concurrent changes; they aren't a signed snapshot.
Validator reuse assumes immutable deployed schemas; restart after schema updates.
Even a passing session audit proves stored-contract consistency only. Coverage over
network failures, causal feature parity, RAM/CPU profiling and economic tests are separate.
Raw event payload hashes cannot be recomputed from the normalized subset alone.

## Local fault evidence
Fixtures cover counts/digests and read-only behavior, mixed-session selection,
depth gap/previous-ID/duplicates, delta without snapshot, duplicate trades,
JSON corruption, incomplete tail, bounded oversized-record draining, count mismatch,
missing session, schema/semantic faults, input mutation, and capped diagnostics.
Actual host data and image runtime acceptance remain pending.
