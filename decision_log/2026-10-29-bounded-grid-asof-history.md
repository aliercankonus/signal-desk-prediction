# Decision: bounded grid as-of state for research momentum

## Status
Proposed for review. No VPS rerun, image build, strategy selection, model training, deployment or result inspection was performed.

## Context and cause
An operator reported that the bounded baseline runner rejected an otherwise verified prefix with `Rolling research history event cap reached` (`size=20001`, `cap=20000`, `ExitCode=2`, `OOMKilled=false`). Those host results are operator reports, not independently inspected evidence. The old history stored every applied state for approximately 65 seconds, even though momentum reads only the latest state at or before each fixed `prediction_at - 60s` cutoff on a 30-second UTC prediction grid. A dense but valid sequence can thus overflow the per-event history cap while the required trade-flow window remains within its limit.

## Representation
Keep three as-of slots for the next prediction tick's 60-second lookback and the following two ticks, plus one latest applied state to bridge event-free intervals: at most **four state references**. Process all earlier prediction ticks before applying a transition. On every transition update all future cutoff slots whose cutoff is at or after the event's applied timestamp; a later event with the same timestamp replaces the prior one. On each tick advance, shift the slots and seed the new farthest cutoff from the latest state if it is not in the future. A cut-off at exactly the event timestamp includes that event. Store the *entire* quote/bridge/depth/trade-freshness state, including invalid and missing-book states; do not search backward for an earlier valid quote. Initialize and update the cache on every event, including warm-up events.

This is only a change to **derived momentum history retention**, not to the 60-second momentum definition or scores. Continue reading and feature-hash verifying every source event in application order. The independent 30-second rolling trade-flow deque still retains all required trades in its inclusive window and rejects more than 20,000 of them, with explicit buffer size and time span. Leave the pinned experiment specification, input/record/output/time limits, labels, prediction grid, fixed strategy weights and immutable publication behavior untouched.

## Evidence and tests
A synthetic 20,001-event same-time history with fewer than 20,000 trades fails the old implementation and passes with the compact cache. A separate 20,001-trade inclusive window still fails. A naive full-history scan on bounded synthetic states checks equal-time ordering, exact cutoff boundaries, invalid states and freshness metadata; full-row reference digests from the pre-optimization implementation match on bounded captures. Existing causality, common-grid, future-append, invalid-lookback and deterministic-output tests remain in the suite. These tests do not establish that the operator's full prefix will pass or that the prefix provides useful research coverage.

## Limits and follow-up
The cache has four references, but trade flow, input bytes, record count, output rows and runtime still have their existing independent caps. A newly built research image and a separately authorized, evidence-preserving operator run would be needed to validate any real prefix; neither is part of this PR. Do not infer strategy efficacy, soak acceptance or permission to train/deploy from local tests.
