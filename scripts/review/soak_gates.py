#!/usr/bin/env python3
"""Fail-closed local gates for an operator-run, review-only continuous soak."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

SID = re.compile(r"[0-9a-f]{32}\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
RAW = re.compile(r"binance_btcusdt_(depth|trade)_\d{4}-\d{2}-\d{2}\.jsonl\Z")
KINDS = ("book_snapshot", "book_delta", "trade")
MAX_RECORD = 4 * 1024 * 1024
MAX_EVENTS = 2_000_000


def positive(value):
    return type(value) is int and value > 0


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def append_counts(raw_dir, pre):
    directory = Path(raw_dir)
    if not directory.is_dir() or not isinstance(pre, dict) or not isinstance(pre.get("files"), dict):
        raise ValueError("Invalid pre-capture inventory")
    old = pre["files"]
    counts = {}
    sequences = {}
    for path in sorted(directory.iterdir()):
        if path.suffix != ".jsonl":
            continue
        match = RAW.fullmatch(path.name)
        if not match:
            raise ValueError("Unrecognized raw JSONL file")
        previous = old.get(path.name, {"size": 0})
        offset = previous.get("size") if isinstance(previous, dict) else None
        if type(offset) is not int or offset < 0:
            raise ValueError("Invalid pre-capture byte offset")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as source:
            before = os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size < offset:
                raise ValueError("Raw file changed or shrank")
            if offset:
                source.seek(offset - 1)
                if source.read(1) != b"\n":
                    raise ValueError("Original raw file ended mid-record")
            source.seek(offset)
            while True:
                line = source.readline(MAX_RECORD + 1)
                if not line:
                    break
                if len(line) > MAX_RECORD or not line.endswith(b"\n"):
                    raise ValueError("Incomplete or oversized appended record")
                try:
                    event = json.loads(line)
                except (ValueError, UnicodeDecodeError) as exc:
                    raise ValueError("Invalid appended record") from exc
                if not isinstance(event, dict) or event.get("event_type") not in KINDS:
                    raise ValueError("Invalid appended event type")
                kind = event["event_type"]
                if (match[1] == "trade") != (kind == "trade"):
                    raise ValueError("Appended event stored in wrong stream")
                quality = event.get("data_quality")
                if not isinstance(quality, dict) or not isinstance(quality.get("collector_session_id"), str):
                    raise ValueError("Missing captured session identity")
                sid = quality["collector_session_id"]
                sequence = quality.get("ingest_sequence")
                if not SID.fullmatch(sid) or quality.get("ordering_version") != "session-applied-v1" or not positive(sequence):
                    raise ValueError("Invalid captured session ordering")
                bucket = counts.setdefault(sid, Counter())
                bucket[kind] += 1
                used = sequences.setdefault(sid, set())
                if sequence in used or len(used) >= MAX_EVENTS:
                    raise ValueError("Duplicate sequence or event budget exhausted")
                used.add(sequence)
            after = os.fstat(source.fileno())
            if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                    after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise ValueError("Raw file changed during count scan")
    sessions = []
    for sid in sorted(counts):
        bucket = counts[sid]
        total = sum(bucket.values())
        if len(sequences[sid]) != total or min(sequences[sid]) != 1 or max(sequences[sid]) != total:
            raise ValueError("Non-contiguous capture sequence")
        sessions.append({"session_id": sid, **{key: bucket[key] for key in KINDS}, "records": total})
    return sessions


def summarize(raw_dir, pre, status, log, state, stats):
    if state.get("Status") != "exited" or state.get("ExitCode") != 0 or state.get("OOMKilled") is not False:
        raise ValueError("Capture did not exit cleanly without OOM")
    if (status.get("status"), status.get("reason"), status.get("mode"), status.get("execution_enabled")) != (
            "STOPPED", "max_run_seconds_reached", "paper", False):
        raise ValueError("Capture did not reach duration stop in paper mode")
    summaries = []
    for line in log.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and value.get("status") in ("STOPPED", "HALT", "RESYNCING"):
            summaries.append(value)
    if len(summaries) != 1 or summaries[0].get("status") != "STOPPED":
        raise ValueError("Collector log has unexpected stop or recovery events")
    fields = ("reason", "session_id", "gap_count", "reconnect_count", "total_written_events",
              "total_depth_events", "total_trade_events")
    if any(status.get(field) != summaries[0].get(field) for field in fields):
        raise ValueError("Status and log counters disagree")
    if (status.get("gap_count"), status.get("reconnect_count")) != (0, 0):
        raise ValueError("Gaps or reconnects observed")
    samples = [json.loads(line) for line in stats.splitlines() if line.strip()]
    if not any(isinstance(sample, dict) and isinstance(sample.get("MemUsage"), str)
               and sample["MemUsage"] and not sample["MemUsage"].startswith("0B") for sample in samples):
        raise ValueError("No live resource sample")
    sessions = append_counts(raw_dir, pre)
    if len(sessions) != 1 or sessions[0]["session_id"] != status.get("session_id"):
        raise ValueError("Expected exactly one new continuous capture session")
    item = sessions[0]
    if item["book_snapshot"] != 1 or not positive(item["book_delta"]) or not positive(item["trade"]):
        raise ValueError("Capture requires snapshot, positive depth and trades")
    for field, observed in (("total_written_events", item["records"]),
                            ("total_depth_events", item["book_delta"]),
                            ("total_trade_events", item["trade"])):
        if not positive(status.get(field)) or status[field] != observed:
            raise ValueError("Recorded collector totals disagree with raw events")
    return {"sessions": sessions, "totals": {"records": item["records"],
            "book_snapshot": item["book_snapshot"], "book_delta": item["book_delta"],
            "trade": item["trade"]}, "stop_reason": "max_run_seconds_reached",
            "resource_samples": len(samples)}


def manifest_from_file(path):
    result = {}
    for line in Path(path).read_text().splitlines():
        if len(line) < 67 or not SHA.fullmatch(line[:64]) or line[64:66] != "  ":
            raise ValueError("Malformed SHA-256 manifest")
        name = Path(line[66:]).name
        if not RAW.fullmatch(name) or name in result:
            raise ValueError("Duplicate or invalid manifest input")
        result[name] = line[:64]
    if not result or len(result) > 64:
        raise ValueError("Raw file manifest must cover 1..64 inputs")
    return result


def verify_raw_set(raw_dir, manifest):
    directory = Path(raw_dir)
    if not directory.is_dir() or not isinstance(manifest, dict) or not manifest:
        raise ValueError("Missing raw file manifest or directory")
    actual = set()
    for path in directory.iterdir():
        if path.suffix == ".jsonl":
            if not RAW.fullmatch(path.name) or not stat.S_ISREG(path.lstat().st_mode):
                raise ValueError("Unexpected or non-regular raw input")
            actual.add(path.name)
    if actual != set(manifest):
        raise ValueError("Raw file set changed after capture")
    return len(actual)


def verify_session(expected, audit, replays, manifest):
    sid = expected.get("session_id")
    counts = {key: expected.get(key) for key in KINDS}
    total = expected.get("records")
    if not isinstance(sid, str) or not SID.fullmatch(sid) or counts["book_snapshot"] != 1 or (
            not positive(counts["book_delta"]) or not positive(counts["trade"]) or
            not positive(total) or sum(counts.values()) != total):
        raise ValueError("Invalid expected captured session")
    if len(replays) != 2 or audit.get("status") != "ok" or audit.get("session_id") != sid or (
            audit.get("counts") != counts or audit.get("selected_records") != total):
        raise ValueError("Audit did not match recorded expected counts")
    def signature(record):
        files = record.get("files")
        if not isinstance(files, list) or len(files) != len(manifest):
            raise ValueError("Audit/replay file inventory incomplete")
        result = {}
        for item in files:
            name = item.get("file")
            if name in result or name not in manifest or item.get("sha256") != manifest[name] or (
                    not isinstance(item.get("bytes"), int) or not isinstance(item.get("lines"), int)):
                raise ValueError("Audit/replay raw file hash mismatch")
            result[name] = (item["sha256"], item["bytes"], item["lines"])
        return result
    base = signature(audit)
    for replay in replays:
        if (replay.get("status") != "ok" or replay.get("session_id") != sid or
            replay.get("counts") != counts or replay.get("records") != total or
            replay.get("last_ingest_sequence") != total or replay.get("capture_hashes_verified") != total or
                replay.get("expected_counts_checked") is not True):
            raise ValueError("Replay did not check every expected captured record")
        if not positive(replay.get("ready_features")) or signature(replay) != base:
            raise ValueError("Replay readiness or raw file evidence mismatch")
    digest = replays[0].get("feature_sha256")
    if not isinstance(digest, str) or not SHA.fullmatch(digest) or replays[1].get("feature_sha256") != digest:
        raise ValueError("Replay feature hashes disagree")
    return {"session_id": sid, "feature_sha256": digest,
            "ready_features": [item["ready_features"] for item in replays],
            "records": total, "files_checked": len(manifest)}


def save_exclusive(path, value):
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        json.dump(value, output, sort_keys=True)
        output.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    summary = sub.add_parser("summarize")
    for name in ("raw-dir", "pre-inventory", "status", "log", "state", "stats", "output"):
        summary.add_argument("--" + name, required=True)
    listing = sub.add_parser("list-sessions")
    listing.add_argument("--summary", required=True)
    raw_set = sub.add_parser("verify-raw-set")
    raw_set.add_argument("--raw-dir", required=True)
    raw_set.add_argument("--manifest", required=True)
    verify = sub.add_parser("verify-session")
    for name in ("summary", "session-id", "audit", "replay-one", "replay-two", "manifest", "output"):
        verify.add_argument("--" + name, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.command == "summarize":
            result = summarize(args.raw_dir, load(args.pre_inventory), load(args.status),
                               Path(args.log).read_text(), load(args.state), Path(args.stats).read_text())
            save_exclusive(args.output, result)
        elif args.command == "list-sessions":
            sessions = load(args.summary)["sessions"]
            if not sessions or len(sessions) != 1:
                raise ValueError("Expected exactly one captured session")
            for item in sessions:
                if not SID.fullmatch(item["session_id"]):
                    raise ValueError("Invalid session ID")
                print(item["session_id"], item["book_snapshot"], item["book_delta"], item["trade"])
        elif args.command == "verify-raw-set":
            verify_raw_set(args.raw_dir, manifest_from_file(args.manifest))
        else:
            entries = load(args.summary)["sessions"]
            matches = [value for value in entries if value.get("session_id") == args.session_id]
            if len(matches) != 1:
                raise ValueError("Session missing or repeated")
            result = verify_session(matches[0], load(args.audit),
                                    [load(args.replay_one), load(args.replay_two)],
                                    manifest_from_file(args.manifest))
            save_exclusive(args.output, result)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"Soak gate failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
