# Decision: reuse checked schemas and diagnose stale pipeline events

## Status
Accepted candidate update, 2026-10-27; VPS repeat pending.

## Context
VPS 60s continuous trial recorded 817 events and two stale-depth resyncs with
gap_count=0. It did not establish stable operation; exit code was not supplied.
The code checked the JSON schema itself on every event and synchronously fsyncs
each event. Network, scheduling and IO contributions cannot be inferred from
the old log line.

## Source checked
https://python-jsonschema.readthedocs.io/en/stable/validate/
Official validator documentation, inspected 2026-10-27, recommends reusing a
specific checked validator when validating multiple instances of a known schema.
The installed project dependency remains jsonschema 4.23.0; no upgrade added.
Before-change source: src/signal_desk/schemas/validate.py at dc8fe839f0da90e35d17c995315eba1246bdef86.

## Decision
Use a bounded 32-entry cache of checked validators, keyed by resolved local schema
path and inode/mtime/ctime/size. Every instance is still validated. A replaced local
schema invalidates this key; invalid schemas still fail closed. Schemas in images
are expected to be immutable; restart to apply external referenced-schema changes.
Keep fsync, queue bounds, CPU cap and freshness thresholds unchanged.
Add bounded maxima/counters, not unbounded samples, for receipt, applied-depth
age, queue depth, event-loop lag, validation and write/IO latency.
Carry diagnostics in stale errors and preserve the last error across recovery.

## Tests and evidence
53 local tests passed plus config/schema validation. Regressions cover invalid
instances after reuse, schema replacement, invalid schemas, stale diagnostics,
timed slow validation and diagnostic preservation across reconnect.
Local isolated 100-event schema-validation timing: 0.6502s uncached / 0.0203s reused.
No whole-system speedup, VPS latency or root-cause resolution claimed.

## Alternatives and risks
Raising stale limits, dropping validation or weakening fsync were not selected.
Caching referenced schemas is not a live schema deployment protocol; deploy immutable
images. Diagnostics have modest overhead and do not prove where network delay began.
The event loop may still block on writes, and tests don't replace VPS measurements.

## Rollback
Revert this candidate commit or use previous collector image. No data/config/schema
migration; preserve the shared volume. Do not start a concurrent collector to compare.
