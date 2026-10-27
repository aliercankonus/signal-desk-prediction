# 12 — External Methods

## Day Trader repository

Adapt these ideas:

- Risk checks.
- Position sizing.
- Exit plans.
- Order-plan fingerprints.

Do not directly adopt:

- US stock assumptions.
- Whole-share/cent precision.
- 15-minute freshness.
- Checks that block crypto.
- Broker workflows.

## ECC

Adapt:

- Latency-critical measurement methods.
- Verification loop.
- Docker patterns.
- Model-independent risk limits from LLM trading security.

Do not add the full package as a runtime dependency.

## Ruflo

Optional offline development/research coordination only; never a dependency of the
live Decision Engine or paper ledger.

## Lessons from quantitative firms

- Share the feature engine between live processing and replay.
- Do not discard events merely because the price is unchanged.
- Measure post-fill markout.
- A timeout may not have stopped the underlying operation.
- Test restart/snapshot/buffer safety.
- A large model does not guarantee profitability.

## Time Machine — accepted additional feature

Apply the [Time Machine contract](16-timemachine.md): scenario simulation and
historical-rule testing separate from existing replay. Source review is complete;
the BTC adaptation is an accepted design, not an implemented simulator.
