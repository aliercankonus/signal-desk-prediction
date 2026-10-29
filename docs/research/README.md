# First strategy research slice: fixed references + S1

**Proposed, not selected or deployed.** The versioned specification is
[`s1_experiment_v1.json`](s1_experiment_v1.json). It was written before any
real experiment results were examined. It proposes Binance BTCUSDT **spot**,
long/flat research, separate 60-second and 300-second midpoint-direction
horizons, a shared 30-second UTC prediction grid, 60-second warm-up, fixed
freshness/spread gates, and a 60-day chronological 36/12/12-day split with
300-second label purge and 300-second post-boundary embargo. Exact UTC window
bounds and sufficient ordered data require a separate review. The final test
may be evaluated once, after validation-only selection. This PR performs **no
parameter search**, threshold selection, or economic comparison.

The runner uses the existing ordered `CausalFeaturePipeline` with the recorded
capture feature policy to verify every capture-time digest; fixed research
freshness/spread gates are independent of that capture policy. It derives a
separate bounded, research-only
30-second signed aggressive-trade quantity window directly from ordered trade
events; neither `top_book_imbalance` nor the existing `*_qty_window` lifetime
counters are rolling order flow. The four fixed scores are no-change zero,
60-second momentum ratio, weighted-midpoint divergence normalized by spread,
and a provisional S1 combination of 70% signed trade ratio and 30% divergence.
The weighted midpoint is a **micro-price proxy**, not a trained/calibrated
micro-price. Scores are not calibrated probabilities or expected returns.
Dedicated live 30-second flow features require a later capture feature-version
change with the exact semantics in the decision log; do not assume live/replay
parity for this research-only overlay.

## Input manifest and bounded local invocation

### Completed raw COPY → bounded prefix (offline only)

`python -m signal_desk.research.extract_prefix` operates on a stopped, completed,
read-only **copy** of the ordered raw directory, not a live collector or VPS volume.
Its CLI is pinned to collector session
`cb8a0767d7284b8aaa3d09fbca7095f2`, whose independently recorded complete
counts must be exactly one snapshot, 35,936 depth deltas and 222,238 trades
(258,175 events). It does not relax the baseline runner's limits. An explicit
Python-only `synthetic_session_id` override exists for synthetic tests; no CLI
override exists for a real source.

Supply a private `completed-raw-copy-v1` source manifest containing
`{"manifest_version":"completed-raw-copy-v1", "session_id":"cb8a0767d7284b8aaa3d09fbca7095f2", "completed":true, "expected_counts":{"book_snapshot":1,"book_delta":35936,"trade":222238}, "expected_feature_sha256":"bafabf00f920c948a7f952425d105197039af0104c0b28b65904afdbe94bf6c0", "files":[{"name":"<actual basename>","bytes":<actual size>,"sha256":"<actual 64-character lowercase SHA-256>"}]}`.
The `files` list must include **every** recognized source JSONL file, including
files with other sessions, with independently obtained exact sizes and SHA-256
values. No source file hashes are invented here; verify and record them privately
from the completed copy before invoking extraction. The completion assertion and
counts must come from the independent collector summary, not inferred from the
extracted prefix. The source manifest itself is not authentication of the exchange.

```bash
PYTHONPATH=src python -m signal_desk.research.extract_prefix \
  --raw-dir /path/to/completed/read-only/raw-copy \
  --source-manifest /path/to/private/completed-raw-copy-v1.json \
  --spec docs/research/s1_experiment_v1.json \
  --output-dir /path/to/new/private/prefix-directory
```

The output directory must not exist and must be outside the source tree. The
raw COPY directory and every recognized raw file must have all write-permission
bits cleared before extraction; this rejects ordinarily writable inputs but does
not prove that collection stopped, that an operator's completion assertion is
true, or that a privileged writer cannot change the copy. Establish completion
and read-only isolation independently; the manifest and mode checks are not
host attestation. The extractor checks the reviewed canonical specification and
its **exact file-byte**
SHA-256; scans the whole source by shared application sequence with the existing
bounded `SessionInput` reader and `CausalFeaturePipeline`, verifies every source
capture feature hash, the ordered full-session feature-output digest reported by
the operator, independently recorded source counts, and all source file
hashes. The pinned aggregate digest is an expected value, not direct evidence
that the private copy has been inspected in this PR. It copies the original
JSONL record bytes into their original stream/day filenames without
resequencing, splitting lines, or changing feature digests.
The prefix starts at sequence 1 and stops *before* the next record would exceed
either 90,000 records or 128 MiB of serialized raw JSONL. It must contain the
starting snapshot and depth bridge. Separate source ceilings are 64 files,
768 MiB (805,306,368 bytes) of predeclared raw input, 350,000 selected source
records, 4 MiB per record, and a cooperative 900-second runtime budget. The
operator-reported collector `raw_bytes=547115599` is a **storage total**, not an
independently verified sum of the recognized raw COPY files. It exceeds the old
512 MiB (536,870,912-byte) source ceiling; 768 MiB provides explicit bounded
headroom without raising the 90,000-record / 128 MiB output caps or any baseline
runner limit. Before execution, derive the **exact recognized source-file sum**
from the completed copy's independently verified manifest (every recognized
file's size and SHA-256); do not substitute reported `raw_bytes` for that sum.
The extractor checks each declared size and the aggregate ceiling before scanning,
then verifies whole-file hashes while streaming the full source. A manifest sum
above 768 MiB must fail closed and needs separate review, not an automatic limit
increase. The source must be stopped; metadata and identity checks detect
ordinary changes, not adversarial races.

On complete verification it writes `extraction-v1.json` (source identity,
per-file hashes, full and selected counts, sequence/timestamp range, selection
policy, output hashes, truncation scope and duration status) and publishes
`research-input-v1.json` **last**. A failure leaves an incomplete directory for
inspection without a valid input manifest; do not treat it as success or rerun
over it. `source_end` means all source events fit; `record_limit`/`byte_limit`
explicitly mark a truncated prefix. Duration below the proposed 60 days is
`insufficient_for_proposed_60_day_split`; even a longer duration would not
approve fixed chronological windows. This is diagnostic prefix consistency, not
a full-session 60-day experiment, exchange completeness, model selection or PnL.
Use the emitted input manifest and output directory as `--input-manifest` and
`--raw-dir` respectively for the baseline invocation below; its independent
100,000-row limit still applies.

Run **offline** on a completed, read-only copy of one supported ordered session,
not on a running collector or VPS production volume. Supply one versioned
`research-input-v1` JSON manifest. Its `session_id` is a 32-character lowercase
hex collector session, `spec_sha256` is the hash of the exact proposed JSON
specification file, whose canonical content is also pinned by the runner;
semantic changes require a new version and review. `expected_counts` are
independently recorded completed snapshot/depth/trade totals, and `files`
covers **every** recognized raw JSONL file in the selected directory with
exact basename, byte size and SHA-256.
Record real values privately; do not use placeholders as evidence. Example
structure only:

```json
{
  "manifest_version": "research-input-v1",
  "session_id": "REPLACE_WITH_RECORDED_32_HEX_SESSION_ID",
  "spec_sha256": "REPLACE_WITH_PROPOSED_SPEC_SHA256",
  "expected_counts": {"book_snapshot": 1, "book_delta": 0, "trade": 0},
  "files": [{"name": "REPLACE_WITH_ACTUAL_RAW_BASENAME",
             "bytes": 0, "sha256": "REPLACE_WITH_ACTUAL_FILE_SHA256"}]
}
```

The zero values above are **not observed results** and cannot pass a meaningful
research comparison; replace all values with the independently audited session
counts and file hashes. After specification review, from a separate local
research checkout:

```bash
PYTHONPATH=src python -m signal_desk.research.baselines \
  --spec docs/research/s1_experiment_v1.json \
  --input-manifest /path/to/private/research-input-v1.json \
  --raw-dir /path/to/completed/ordered/raw-copy \
  --output /path/to/new/private/research-diagnostics.jsonl
```

The output path must not exist and must be outside raw input. The runner
checks file names/sizes/hashes, ordered sequence, stored feature hashes and
independently recorded event counts; writes a 0600 no-overwrite diagnostic
JSONL only after full success. Metadata JSON reads are capped at 64 KiB for the
specification and 1 MiB for the manifest; raw byte bounds are checked before
hashing. It caps input at 64 files/256 MiB, 200,000
records, 100,000 output rows, 20,000 retained quote/trade events per rolling
window and a cooperative 600-second runtime budget. Larger data needs a
separately reviewed bounded session/window extraction, not an increased VPS
training load. No legacy timestamp sort or unsupported-order fallback exists.

Every candidate/horizon retains a row at each shared prediction time with
`prediction_status` (`valid`, `invalid`, `no_output`), `raw_score` or null,
`quality_reason`, `label_status` (`valid`, `invalid`, `pending`) and the
midpoint-direction label or null. A pending label means the session ended
before `due_at`; an invalid label means the last applied quote at/before due
failed the same fixed freshness, bridge and spread checks. An earlier quote
cannot replace a later invalid one, and no quote after `due_at` fills the
label. Compare only
common valid prediction/label timestamps within each **separate** horizon;
retain all excluded rows for coverage/quality diagnostics. This single-session
runner does not assign train/validation/test windows or select a winner.

## Next PR, not in this slice

Implement one shared **conservative** paper-fill, risk and append-only ledger
core, with versioned fee/slippage assumptions obtained from verified venue
records, no touch-only passive fills, stop-first interval ambiguity, partial
fill/cancel race, stale/gap blocks, reconciliation and restart tests. Both S0
and S1 must consume the **same** core and identical prediction times. Until
that core and forward paper evidence are validated, report prediction
coverage/direction diagnostics only—**no strategy PnL, economic winner,
profitability claim or real orders**. Exchange fees are unknown here, not
invented. Time Machine remains a separate feature.
