"""Bounded merge of two append-only streams by captured application sequence."""
import argparse
from contextlib import ExitStack
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
import time

from signal_desk.features.causal import (CausalFeaturePipeline, FEATURE_VERSION,
                                       ORDERING_VERSION, canonical_bytes, feature_digest)

MAX_RECORD_BYTES = 4 * 1024 * 1024
MAX_FILES = 64
MAX_OUTPUT_BYTES = 256 * 1024 * 1024


class ReplayError(ValueError):
    pass


class LegacyOrderingError(ReplayError):
    pass


def identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def inventory(directory):
    result = {}
    with os.scandir(directory) as entries:
        for entry in entries:
            match = re.fullmatch(r"binance_btcusdt_(depth|trade)_\d{4}-\d{2}-\d{2}\.jsonl", entry.name)
            if not match:
                if entry.name.endswith(".jsonl"):
                    raise ReplayError("Unrecognized raw JSONL filename")
                continue
            info = entry.stat(follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode):
                raise ReplayError("Raw input must be a regular file, not a symlink")
            if len(result) >= MAX_FILES:
                raise ReplayError("Raw inventory exceeds the 64-file cap; select a bounded directory")
            result[entry.name] = identity(info)
    if not result:
        raise ReplayError("No supported raw files found")
    return result


def reject_constant(value):
    raise ReplayError("Non-standard JSON constant")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReplayError("Duplicate JSON object key")
        result[key] = value
    return result


class SessionInput:
    def __init__(self, directory, session_id, deadline, record_limit):
        self.directory, self.session_id = directory, session_id
        self.deadline, self.record_limit = deadline, record_limit
        self.before = inventory(directory)
        self.files = {}

    def check_deadline(self):
        if time.monotonic() > self.deadline:
            raise ReplayError("Replay runtime budget exhausted")

    def stream(self, kind):
        last_seq = 0
        for name in sorted(n for n in self.before if f"_{kind}_" in n):
            digest = hashlib.sha256()
            lines = selected = size = 0
            path = self.directory / name
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as source:
                if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                    raise ReplayError("Input is not a regular file")
                if identity(os.fstat(source.fileno())) != self.before[name]:
                    raise ReplayError("Raw file changed before scanning")
                while True:
                    self.check_deadline()
                    raw = source.readline(self.record_limit + 1)
                    if not raw:
                        break
                    lines += 1
                    if len(raw) > self.record_limit:
                        raise ReplayError(f"Oversized raw record: {name}:{lines}")
                    if not raw.endswith(b"\n"):
                        raise ReplayError(f"Incomplete raw record: {name}:{lines}")
                    digest.update(raw)
                    size += len(raw)
                    try:
                        event = json.loads(raw, parse_constant=reject_constant, object_pairs_hook=unique_object)
                    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
                        raise ReplayError(f"Invalid JSON: {name}:{lines}") from exc
                    if not isinstance(event, dict):
                        raise ReplayError("Raw record must be an object")
                    quality = event.get("data_quality")
                    if not isinstance(quality, dict) or quality.get("collector_session_id") != self.session_id:
                        continue
                    if quality.get("ordering_version") != ORDERING_VERSION:
                        raise LegacyOrderingError("Selected session lacks application ordering; recapture required")
                    seq = quality.get("ingest_sequence")
                    if type(seq) is not int or seq <= last_seq:
                        raise ReplayError("Per-stream ingest sequence is duplicate or reversed")
                    event_type = event.get("event_type")
                    if (kind == "depth" and event_type not in {"book_snapshot", "book_delta"}) or (
                            kind == "trade" and event_type != "trade"):
                        raise ReplayError("Event is stored in the wrong stream file")
                    last_seq = seq
                    selected += 1
                    yield event
                if identity(os.fstat(source.fileno())) != self.before[name]:
                    raise ReplayError("Raw file changed during scanning")
            self.files[name] = {"file": name, "bytes": size, "lines": lines,
                                "selected_records": selected, "sha256": digest.hexdigest()}

    def merged(self):
        # Two one-record lookaheads, not a heap/list of historical events.
        with ExitStack() as stack:
            from contextlib import closing
            streams = [stack.enter_context(closing(self.stream(kind))) for kind in ("depth", "trade")]
            heads = [next(stream, None) for stream in streams]
            while any(head is not None for head in heads):
                self.check_deadline()
                active = [i for i in (0, 1) if heads[i] is not None]
                selected = min(active, key=lambda i: heads[i]["data_quality"]["ingest_sequence"])
                yield heads[selected]
                heads[selected] = next(streams[selected], None)
        if inventory(self.directory) != self.before:
            raise ReplayError("Raw inventory changed during replay")


def replay_session(raw_dir, session_id, *, output_path=None, max_record_bytes=MAX_RECORD_BYTES,
                   max_output_bytes=MAX_OUTPUT_BYTES, max_runtime_seconds=600, expected=None):
    """Replay a completed session and verify every stored capture feature hash.

    Legacy sessions are explicitly unsupported: receipt or venue timestamps do
    not recover the snapshot/buffer application order. No legacy fallback exists.
    Output is optional, atomic, never appended/overwritten and outside raw_dir.
    """
    if not isinstance(session_id, str) or not 1 <= len(session_id) <= 128:
        raise ReplayError("A session ID of 1..128 characters is required")
    if type(max_record_bytes) is not int or not 1 <= max_record_bytes <= MAX_RECORD_BYTES:
        raise ReplayError("Record budget must be within 1..4 MiB")
    if type(max_output_bytes) is not int or not 1 <= max_output_bytes <= MAX_OUTPUT_BYTES:
        raise ReplayError("Output budget must be within 1..256 MiB")
    if not isinstance(max_runtime_seconds, (int, float)) or not math.isfinite(max_runtime_seconds) or not 0 < max_runtime_seconds <= 3600:
        raise ReplayError("Runtime budget must be within 0..3600 seconds")
    for kind, value in (expected or {}).items():
        if kind not in {"book_snapshot", "book_delta", "trade"} or type(value) is not int or value < 0:
            raise ReplayError("Invalid expected count")
    directory = Path(raw_dir).resolve(strict=True)
    if not directory.is_dir():
        raise ReplayError("Raw directory does not exist")
    output = Path(output_path).absolute() if output_path is not None else None
    if output is not None:
        parent = output.parent.resolve(strict=True)
        if parent == directory or parent.is_relative_to(directory):
            raise ReplayError("Feature output must be outside raw input directory")
        output = parent / output.name
        if output.exists() or output.is_symlink():
            raise FileExistsError("Feature output already exists")
    deadline = time.monotonic() + max_runtime_seconds
    source = SessionInput(directory, session_id, deadline, max_record_bytes)
    counts = {"book_snapshot": 0, "book_delta": 0, "trade": 0}
    digest = hashlib.sha256()
    written = ready_count = records = 0
    pipeline = None
    temp = None
    try:
        with ExitStack() as stack:
            destination = None
            if output is not None:
                fd, temp = tempfile.mkstemp(prefix=".replay-", suffix=".tmp", dir=output.parent)
                destination = stack.enter_context(os.fdopen(fd, "wb"))
            for event in source.merged():
                quality = event["data_quality"]
                if quality.get("feature_version") != FEATURE_VERSION:
                    raise ReplayError("Unsupported capture feature version")
                if pipeline is None:
                    if not isinstance(quality.get("feature_policy"), dict):
                        raise ReplayError("Captured feature policy missing")
                    pipeline = CausalFeaturePipeline(session_id, quality["feature_policy"])
                snapshot = pipeline.apply(event)
                stored = quality.get("feature_sha256")
                if not isinstance(stored, str) or not re.fullmatch(r"[0-9a-f]{64}", stored):
                    raise ReplayError("Captured feature hash missing or malformed")
                if feature_digest(snapshot) != stored:
                    raise ReplayError(f"Capture/replay feature mismatch at sequence {pipeline.sequence}")
                raw = canonical_bytes(snapshot) + b"\n"
                if written + len(raw) > max_output_bytes:
                    raise ReplayError("Feature output byte budget exhausted")
                source.check_deadline()
                if destination is not None:
                    destination.write(raw)
                digest.update(raw)
                written += len(raw)
                records += 1
                ready_count += int(snapshot["data_quality"]["ready"])
                counts[event["event_type"]] += 1
            if pipeline is None:
                raise ReplayError("Selected session not found")
            if not pipeline.bridged:
                raise ReplayError("Selected session has no depth bridge")
            for kind, value in (expected or {}).items():
                if counts[kind] != value:
                    raise ReplayError(f"Expected {kind}={value}, observed {counts[kind]}")
            source.check_deadline()
            if destination is not None:
                destination.flush()
                os.fsync(destination.fileno())
        # No overwrite even if another process created the final path during replay.
        source.check_deadline()
        if inventory(directory) != source.before:
            raise ReplayError("Raw inventory changed before publication")
        if output is not None:
            os.link(temp, output)
        return {"status": "ok", "session_id": session_id, "ordering_version": ORDERING_VERSION,
                "feature_version": FEATURE_VERSION, "records": records, "counts": counts,
                "capture_hashes_verified": records, "ready_features": ready_count,
                "expected_counts_checked": set(expected or {}) == set(counts),
                "feature_bytes": written, "feature_sha256": digest.hexdigest(),
                "last_ingest_sequence": pipeline.sequence,
                "files": [source.files[name] for name in sorted(source.files)],
                "scope": "stored-session capture/replay feature parity; not exchange completeness, model or PnL"}
    finally:
        if temp is not None:
            Path(temp).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", default="/data/raw")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--output")
    parser.add_argument("--max-runtime-seconds", type=float, default=600)
    parser.add_argument("--max-output-bytes", type=int, default=MAX_OUTPUT_BYTES)
    parser.add_argument("--expected-snapshots", type=int)
    parser.add_argument("--expected-depth", type=int)
    parser.add_argument("--expected-trades", type=int)
    args = parser.parse_args()
    expected = {kind: value for kind, value in (("book_snapshot", args.expected_snapshots),
                ("book_delta", args.expected_depth), ("trade", args.expected_trades)) if value is not None}
    try:
        result = replay_session(args.raw_dir, args.session_id, output_path=args.output,
                                max_runtime_seconds=args.max_runtime_seconds,
                                max_output_bytes=args.max_output_bytes, expected=expected)
    except LegacyOrderingError as exc:
        print(json.dumps({"status": "unsupported", "reason": str(exc)}), flush=True)
        return 2
    except Exception as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)[:240]}), flush=True)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
