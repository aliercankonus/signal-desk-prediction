"""Read-only, record-bounded audit of one collector session in raw JSONL."""
import argparse
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re

from signal_desk.schemas.validate import validate_json, SchemaValidationError


MAX_RECORD_BYTES = 4 * 1024 * 1024


def _identity(stat):
    return stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _reject_constant(value):
    raise ValueError(f"Non-standard JSON constant: {value}")


def audit_session(raw_dir, session_id, *, expected=None, max_record_bytes=MAX_RECORD_BYTES):
    if not session_id or not 1 <= max_record_bytes <= MAX_RECORD_BYTES:
        raise ValueError("Session ID and a record limit within 1..4 MiB are required")
    directory = Path(raw_dir)
    if not directory.is_dir():
        raise ValueError("Raw directory does not exist")
    paths = sorted(directory.glob("*.jsonl"))
    if not paths:
        raise ValueError("No raw JSONL files found")
    before = {str(p): _identity(p.stat()) for p in paths}
    errors, samples, counts, files = Counter(), [], Counter(), []
    last_depth_id = None
    last_trade_id = None

    def fail(kind, path="", line=0, detail=""):
        errors[kind] += 1
        if len(samples) < 5:
            samples.append({"error": kind, "file": Path(path).name if path else "",
                            "line": line, "detail": str(detail)[:240]})

    def check_event(event, path, line):
        nonlocal last_depth_id, last_trade_id
        kind = event.get("event_type")
        counts[kind if isinstance(kind, str) and kind in {"trade", "book_delta", "book_snapshot"} else "unsupported"] += 1
        try:
            validate_json(event, "market_event.schema.json")
        except SchemaValidationError as exc:
            fail("schema", path, line, exc)
            return
        try:
            for key in ("exchange_ts", "received_ts"):
                value = datetime.fromisoformat(event[key].replace("Z", "+00:00"))
                if value.tzinfo is None:
                    raise ValueError(f"{key} has no timezone")
            if not re.fullmatch(r"[0-9a-f]{64}", event["payload_hash"]):
                raise ValueError("payload_hash must be a SHA-256 hex string")
            if kind in {"book_snapshot", "book_delta"}:
                for side in ("bids", "asks"):
                    if not isinstance(event.get(side), list):
                        raise ValueError(f"{side} missing from depth event")
                    for price, quantity in event[side]:
                        if Decimal(price) <= 0 or Decimal(quantity) < 0:
                            raise ValueError("Nonpositive price or negative depth quantity")
                if kind == "book_snapshot":
                    value = event.get("last_update_id")
                    if type(value) is not int or value < 0:
                        raise ValueError("Invalid snapshot update ID")
                    last_depth_id = value
                else:
                    first, final = event.get("first_update_id"), event.get("final_update_id")
                    if type(first) is not int or type(final) is not int or first > final:
                        raise ValueError("Invalid depth update range")
                    if last_depth_id is None:
                        fail("depth_without_snapshot", path, line)
                    else:
                        if final <= last_depth_id:
                            fail("duplicate_or_old_depth", path, line)
                        if first > last_depth_id + 1:
                            fail("depth_gap", path, line, f"expected {last_depth_id + 1}, first {first}")
                        if event.get("previous_final_update_id") != last_depth_id:
                            fail("previous_depth_id", path, line)
                    last_depth_id = max(final, last_depth_id if last_depth_id is not None else final)
            elif kind == "trade":
                value = event.get("trade_id")
                if isinstance(value, bool) or value is None:
                    raise ValueError("Missing or invalid trade_id")
                value = int(value)
                if last_trade_id is not None and value <= last_trade_id:
                    fail("duplicate_or_reordered_trade", path, line)
                # ID gaps are not treated as proof of missed market trades.
                last_trade_id = value
                if Decimal(event["trade_price"]) <= 0 or Decimal(event["trade_qty"]) <= 0:
                    raise ValueError("Trade price and quantity must be positive")
                maker = event.get("is_buyer_maker")
                if type(maker) is not bool or event.get("trade_side") != ("sell" if maker else "buy"):
                    raise ValueError("Trade aggressor side does not match buyer-maker flag")
            else:
                fail("unsupported_event", path, line, kind)
        except (ValueError, TypeError, KeyError, InvalidOperation) as exc:
            fail("event_semantics", path, line, exc)

    for path in paths:
        digest, scanned, selected, lines = hashlib.sha256(), 0, 0, 0
        with path.open("rb") as source:
            while True:
                raw = source.readline(max_record_bytes + 1)
                if not raw:
                    break
                lines += 1
                digest.update(raw)
                scanned += len(raw)
                if len(raw) > max_record_bytes:
                    # Drain an oversized line in bounded chunks and still hash all bytes.
                    while raw and not raw.endswith(b"\n"):
                        raw = source.readline(max_record_bytes + 1)
                        digest.update(raw)
                        scanned += len(raw)
                    fail("oversized_record", path, lines)
                    continue
                if not raw.endswith(b"\n"):
                    fail("unterminated_record", path, lines)
                if not raw.strip():
                    fail("blank_record", path, lines)
                    continue
                try:
                    event = json.loads(raw, parse_constant=_reject_constant)
                    if not isinstance(event, dict):
                        raise ValueError("Record must be an object")
                except (ValueError, UnicodeDecodeError) as exc:
                    fail("json", path, lines, exc)
                    continue
                quality = event.get("data_quality")
                if not isinstance(quality, dict) or quality.get("collector_session_id") != session_id:
                    continue
                selected += 1
                check_event(event, path, lines)
            if _identity(os.fstat(source.fileno())) != before[str(path)]:
                fail("file_changed", path)
        files.append({"file": path.name, "bytes": scanned, "lines": lines,
                      "selected_records": selected, "sha256": digest.hexdigest()})

    after_paths = sorted(directory.glob("*.jsonl"))
    after = {str(p): _identity(p.stat()) for p in after_paths}
    if before != after:
        fail("raw_inventory_changed")
    selected_total = sum(counts.values())
    if not selected_total:
        fail("session_not_found")
    if counts["book_snapshot"] == 0:
        fail("snapshot_missing")
    for kind, number in (expected or {}).items():
        if number < 0 or kind not in {"book_snapshot", "book_delta", "trade"}:
            raise ValueError("Invalid expected count")
        if counts[kind] != number:
            fail("count_mismatch", detail=f"{kind}: expected {number}, got {counts[kind]}")
    return {"status": "ok" if not errors else "failed", "session_id": session_id,
            "selected_records": selected_total, "counts": dict(counts),
            "last_depth_update_id": last_depth_id, "last_trade_id": last_trade_id,
            "error_counts": dict(errors), "error_samples": samples, "files": files,
            "max_record_bytes": max_record_bytes,
            "scope": "raw-session audit; not live/replay parity or exchange completeness"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", default="/data/raw")
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--expected-snapshots", type=int)
    parser.add_argument("--expected-depth", type=int)
    parser.add_argument("--expected-trades", type=int)
    args = parser.parse_args()
    expected = {kind: value for kind, value in [
        ("book_snapshot", args.expected_snapshots), ("book_delta", args.expected_depth),
        ("trade", args.expected_trades)] if value is not None}
    try:
        result = audit_session(args.raw_dir, args.session_id, expected=expected)
    except Exception as exc:
        print(json.dumps({"status": "error", "reason": str(exc)[:240]}), flush=True)
        return 1
    print(json.dumps(result, sort_keys=True, indent=2), flush=True)
    return 0 if result["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
