# 13 — External Methods Incorporated

## Day Trader Skill

Adapt:

- Risk checks before intent.
- Position sizing as the minimum of risk, cash and max-notional constraints.
- Exit plans before entry.

Required changes:

- Replace US stock assumptions with BTC decimal lot/step precision.
- Do not accept prices stale by 15 minutes.
- Separate daily loss and risk reservation.

## ECC

Adapt:

- Latency-critical measurement: p50/p95/p99, stale data and queue depth.
- Verification loop.
- Docker patterns.
- Model-independent risk limits from LLM trading security.

Do not add the full package as a runtime dependency.

## Ruflo

Optional offline development/research coordination only; never a dependency of the
live Decision Engine or paper ledger.

## Lessons from quantitative firms

- Jane Street: shared live/replay event-driven feature engine; preserve distinct same-price events.
- Optiver: a fill does not establish a good trade; measure markout.
- XTX/Optiver: larger models do not guarantee persistent edge; monitor degradation and overfitting.

## Adding research sources

Add every external method with a source and decision-log entry under
`references/15-research-decision-policy.md`.

## Time Machine — accepted additional feature

Apply the [Time Machine contract](16-timemachine.md): scenario simulation and
historical-rule testing separate from existing replay. Source review is complete;
the BTC adaptation is an accepted design, not an implemented simulator.
