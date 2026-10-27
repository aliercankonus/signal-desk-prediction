# 09 — Paper Fill Model

A paper fill is not a real fill. Every record includes mode, assumptions, fees,
slippage and markout fields.

## Modes

| Mode | Purpose |
| --- | --- |
| `conservative` | Primary acceptance mode; adverse case when uncertain |
| `neutral` | Normal analysis; reasonable but unguaranteed assumptions |
| `optimistic` | Sensitivity analysis; not used for success claims |

## Conservative rules

- A touch alone is insufficient for a nonmarketable limit entry; require enough opposing trade volume or a queue proxy.
- If stop and target both occur within the same interval, use stop-first.
- For spread crossing, apply taker fees and conservative slippage.
- Support partial fills; unfilled quantity remains open risk or is cancelled after expires_at.
- Do not record new fills when data is stale or gapped.

## Neutral rules

- A touch plus sufficient volume proxy may support a partial fill.
- Use event sequence for stop/target ordering when known; otherwise fall back to conservative behavior.
- Derive slippage from a measured spread/volatility model.

## Optimistic rules

- A touch may be accepted as a fill.
- Stop/target ambiguity must not become target-first; at most use neutral sequence or a middle assumption.
- Reports must carry the label “not for acceptance”.

## Markout

Measure midpoint markout for each fill at:

- 1s
- 5s
- 30s
- 60s
- 300s

Use post-fill price behavior to diagnose adverse selection. Markout does not replace net PnL.

## Cancel race and restart

- Late fills may arrive after cancel requests; prevent overselling.
- No new ENTER until ledger reconciliation completes after restart.
- Persist cumulative and remaining quantities for partial fills.
