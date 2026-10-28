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
