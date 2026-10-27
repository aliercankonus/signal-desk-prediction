# Decision: Time Machine as a separate research feature

## Status

Accepted feature contract; implementation pending. 2026-10-27.

## Context

The user requested Time Machine in the skills as a feature separate from existing replay.

## Sources checked

On 2026-10-27, reviewed trader-timemachine/SKILL.md, timemachine.py,
tests/test_timemachine.py and LICENSE at Jakeschincariol/day-trader-skill commit
3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd. Pinned links are in
references/16-timemachine.md. Source tests were not run here.

## Decision

Accept references/16-timemachine.md. Separate synthetic scenarios from real
historical-rule evaluation. Label the source's independent-bar method as a reference;
block bootstrap is not yet selected. Apply BTC 24/7 UTC, point-in-time data, explicit
costs and stop gaps. Config/schemas and src/signal_desk/timemachine are future work;
no runtime was added by this decision.

## Alternatives

Rejected converting the replay runner into simulation: they serve different purposes.
Rejected unchanged US-session/Yahoo/ORB assumptions and treating Monte Carlo ratios
as calibrated predictions or live risk vetoes.

## Risks

Independent-bar sampling may break serial dependence; 10,000 paths are not 10,000
independent market observations. Five-minute OHLC cannot establish a 60s target or
historical L2 S1 results. The source's −1R stop assumption hides gap costs. Each is
addressed explicitly by constraints/tests in the contract.

## Tests added

Documentation only; no executable tests added. Acceptance scenarios in
references/16-timemachine.md are implementation requirements. Verify references,
links, existing skill frontmatter and remote content integrity for this update.
No VPS, Docker or simulation success is claimed.

## Rollback

Revert the Time Machine reference/section. No data/runtime migration is required,
because replay, risk and collector code are unchanged.
