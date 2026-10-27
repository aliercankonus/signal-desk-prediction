# 13 — Acceptance Gates

## Gates

| Gate | Output |
| --- | --- |
| G0 | Scope/config/project state |
| G1 | Docker skeleton |
| G2 | Binance BTCUSDT collector |
| G3 | Storage/replay/checkpoint |
| G4 | Feature + baseline + paper core |
| G5 | Model comparison |
| G6 | Forward paper |
| G7 | Portable clean-host restore |
| G8 | 200GB migration drill |

## Fault tests

- Kill while engine is `FLAT` → recover flat.
- Kill after `PENDING_SEND` → no duplicate intent.
- Partial fill + cancel race → preserve filled quantity.
- L2 stale → ENTER BLOCK.
- Trade stale → ENTER BLOCK.
- Fee stale → ENTER BLOCK or stress fee.
- Ledger write failure → HALT.
- Disk 85% → ENTER BLOCK.
- Disk 95% → HALT.
- Stop + TP in the same interval → conservative stop-first.
- Buffer requested before snapshot → explicit error, no zero-fill.
- EOD rerun → revision, no duplicate result.
- 200GB migration → preserve hashes/manifests.

## Separate success claims

Report each independently:

1. Data is flowing.
2. Replay is correct.
3. Predictions are produced.
4. Risk/decision processing works.
5. Paper fills are consistent.
6. Economic results are positive.
7. Portable restore passed.

None of these proves another.
