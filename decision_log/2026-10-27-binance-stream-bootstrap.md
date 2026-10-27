# Decision: buffer Binance depth before REST snapshot

## Status
Accepted implementation fix, 2026-10-27; VPS retest pending.

## Context
User VPS smoke exited 2 with RESYNCING: expected 101957348207, first received
101957348292. Previous implementation fetched the snapshot before connecting WS.

## Sources checked
Official Binance Spot documentation, inspected 2026-10-27:
https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md#how-to-manage-a-local-order-book-correctly
Retrieved file blob: c6f455b600d83b4e048dac0876df42eaba8e7b71.
The official procedure opens WS, buffers depth, fetches REST, retries old snapshots,
drops covered deltas and restarts synchronization after a true sequence gap.

## Decision
Open WS first. Start a dedicated receiver, wait for first depth and retain earlier
trade messages. Fetch REST in asyncio.to_thread so receipt continues. Retry a
snapshot behind the first buffered U at most 3 times. Ignore depth u <= local ID;
require a valid depth bridge before RUNNING or smoke success.
Store previous_final_update_id before advancing the book.
Print terminal JSON on both synchronization and connection failure.

Smoke bounds: 256 queued events, 256 KiB WS message cap, WS internal max_queue=16,
10s market-event waits, 10s REST requests, 3 snapshot attempts. Overflow/timeout
fails closed with exit 2. These are conservative engineering bounds for the smoke
path, not validated continuous-run capacity settings. Central config exposure,
automatic reconnect/resync and retention remain future work.

## Alternatives
Keep snapshot-first or ignore gaps: rejected because it loses sequence coverage.
Unbounded buffering/retry: rejected for the 2GB project budget.
Continuous automatic recovery: deferred; this fix makes the bounded smoke correct
and diagnostic, and continues to stop on genuine gaps.

## Tests added
tests/collector/test_stream_bootstrap.py: receive during REST, stale snapshot retry,
genuine gap, trade-only refusal, snapshot retry exhaustion, buffer overflow,
duplicate depth discard, connection error diagnostics and receiver cleanup.
Existing 16 plus 8 new tests: 24 passed locally. Config/schema validation passed.
VPS image rebuild and live 25-event smoke have not yet been rerun with this fix.

## Rollback
Return to the previous image/code; do not truncate or delete /data.
No config, schema or storage migration. API readiness and execution=false unchanged.
