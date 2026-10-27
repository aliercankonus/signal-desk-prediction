# 08 — Paper Fill Model

Three paper-fill modes are defined. **Conservative** is the primary acceptance mode.

## Modes

| Mode | Use | Assumption |
| --- | --- | --- |
| Conservative | Acceptance and risk | Adverse case when uncertain |
| Neutral | Normal daily reporting | Middle assumption |
| Optimistic | Sensitivity analysis | Near-best case, labeled separately |

## Shared principles

- A triggered stop does not guarantee an actual fill.
- If stop and target are both visible within the same interval, conservative mode uses stop-first.
- A filled limit order does not establish a good trade; measure markout.
- Preserve partial-fill quantities.
- A cancel request is not a cancel confirmation.
- After restart, reconcile the paper ledger against its own persistent records, not the exchange.
- Do not apply futures/funding/liquidation assumptions to V0 spot paper trading.

## Markout measurements

For each paper fill:

- fill_time
- fill_price
- midpoint at +1s, +5s, +30s, +60s
- spread at fill
- fee estimate
- slippage estimate
- adverse selection flag

Markout is a diagnostic metric, not net profit or model acceptance.
