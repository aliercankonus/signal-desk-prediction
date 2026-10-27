# Decision: bounded continuous collection with full resynchronization

## Status
Accepted implementation candidate, 2026-10-27; pending VPS validation.

## Context
The bootstrap fix passed 24 tests and bounded 25/1,000-record live runs on the VPS.
A continuously running service still needs reconnection, resync and resource bounds.

## Sources checked
- Official Binance Spot WebSocket streams, inspected 2026-10-27:
  https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md
  File blob: c6f455b600d83b4e048dac0876df42eaba8e7b71. Covers 24h disconnection, serverShutdown,
  ping/pong, connection limits, and rebuilding a local book after missed depth.
- Python asyncio subprocess API:
  https://github.com/python/cpython/blob/main/Doc/library/asyncio-subprocess.rst
  Use create_subprocess_exec with argv, communicate, and explicit kill/reap on timeout.
- Docker resource constraints:
  https://docs.docker.com/engine/containers/resource_constraints/
  Runtime CPU/memory caps are configuration mechanisms; this project's caps are
  engineering budget choices, not proof of measured resource consumption.

## Decision and rationale
Implement opt-in continuous mode around independent, fresh bootstrap sessions.
Use bounded exponential retries (1s to 30s, 5 failures); reset only after 60s stable
progress. Stop on permanent HTTP/rate limiting, data/schema or storage errors.
Explicit numeric defaults are conservative project choices, not Binance requirements.
Use a cancellable REST child rather than a thread that could survive cancellation.
Validate optional centralized collector policy with backward compatible defaults.
Keep Compose idle until accepted. No Docker automatic restart around HALT.
Keep 512 MiB memory cap and add 0.75 CPU/64 PID caps plus bounded Docker logs.
Enforce current raw pool/disk HALT budgets without deleting history.
Tag sessions, keep cumulative diagnostics, and atomically replace status.

## Alternatives
Blind reconnect without snapshot, unlimited retries, and always-restart rejected.
A single good event does not prove a stable session. Background training or LLM calls
are unrelated. Heavy new HTTP libraries are avoided with an isolated request helper.

## Tests added
Local suite 49 passed, config/schema validation passed.
See references/17-continuous-collector.md for fault and local HTTP coverage.
Existing tests remain; VPS rebuild/60s candidate and live fault recovery are pending.

## Risks and limits
Kernel disk usage isn't reserved against other processes. Raw inventory assumes one
collector; a lock prevents a second continuous writer but not independent smoke writers.
No TTL/compression, 24h soak, replay parity, stop-loss, order or economic claims.
A HALT process needs inspection and manual restart. Power failure may leave status stale:
consumers must check timestamp and process liveness; no integrated risk gate added.

## Rollback
Return to main/previous image and idle mode. Preserve the shared data volume.
The optional collector section is additive; existing active v16 config remains usable.
