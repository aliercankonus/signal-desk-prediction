# 14 — Acceptance Gates

## G0 — Spec completeness

- SKILL references complete.
- Schemas valid JSON Schema.
- Config schema valid.
- Binance adapter spec exists.

## G1 — Config/schema validation

- `config.example.yaml` validates.
- Sample market events validate.
- Invalid config fails closed.

## G2 — Clean-host deployment skeleton

- `docker compose config -q` passes.
- `docker compose up -d --wait` passes.
- `/health/live`, `/health/ready`, `/health/paper` work.

## G3 — Binance market data

- Depth stream connected.
- Snapshot bootstrap passes.
- Gap detection/resync passes.
- Trade side mapping passes.
- Raw Zstd event written.

## G4 — Feature/replay causality

- Same raw events produce same features.
- Future data leakage test passes.
- Missing buffer produces explicit error, not zero-fill.

## G5 — Decision/risk

- ENTER/HOLD/EXIT/WAIT/BLOCK/HALT tests pass.
- Daily loss latch works.
- Duplicate intent prevented.
- Ledger write failure HALTs.

## G6 — Paper fill

- Conservative stop-first test passes.
- Partial fill + cancel race test passes.
- Restart reconcile test passes.
- Markout computed.

## G7 — EOD/observability

- EOD idempotent revision test passes.
- Alarm thresholds produce expected actions.
- Disk/RAM fake pressure tests pass.

## G8 — 24h paper soak

- 24h BTCUSDT paper-only run.
- No live execution.
- No unreconciled ledger state.
- EOD generated.
- Resource limits stay within profile.

## G9 — Forward research

- Model comparison uses frozen validation/final windows.
- Final test run once.
- Negative results preserved.

## TM — Time Machine research acceptance (pending)

Does not automatically advance G0–G9 or block the initial VPS smoke test.
After implementation, verify causality, determinism, horizons, costs/gaps, separate
historical-rule tests and resource-limit scenarios in references/16-timemachine.md.
The simulator, schemas and tests do not exist yet; acceptance has not been granted.
