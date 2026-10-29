#!/usr/bin/env python3
"""Bounded offline validation of a completed research prefix before operator success."""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys

SID = "cb8a0767d7284b8aaa3d09fbca7095f2"
COUNTS = {"book_snapshot": 1, "book_delta": 35936, "trade": 222238}
FEATURE_SHA = "bafabf00f920c948a7f952425d105197039af0104c0b28b65904afdbe94bf6c0"
SPEC_SHA = "da685a83c357ee880ae7d0ca6ef6b9bee0051a737b90200c22ee832c3b8d50d3"
MAX_RECORDS = 90000
MAX_BYTES = 128 * 1024 * 1024
MAX_SOURCE_BYTES = 768 * 1024 * 1024
MAX_FILES = 64
MAX_RECORD_BYTES = 4 * 1024 * 1024
SCOPE = "verified stored source and raw prefix; not full-session research, exchange completeness, model selection or PnL"
METADATA_CAP = 1024 * 1024
OUTPUT_METADATA_CAP = 65536
HEX = re.compile(r"[0-9a-f]{64}\Z")
NAME = re.compile(r"[A-Za-z0-9_.-]+\.jsonl\Z")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _constant(value):
    raise ValueError("Nonfinite JSON constant: " + value)


def _regular(path, cap):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > cap:
        raise ValueError("Nonregular or over-budget file: " + str(path))
    return info


def _read(path, cap):
    before = _regular(path, cap)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        if os.fstat(stream.fileno()).st_size != before.st_size:
            raise ValueError("File changed before read")
        data = stream.read(before.st_size)
        if len(data) != before.st_size or stream.read(1) or _identity(os.fstat(stream.fileno())) != _identity(before):
            raise ValueError("File changed during read")
    return data


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _json(path, cap):
    return json.loads(_read(path, cap), object_pairs_hook=_unique, parse_constant=_constant)


def _digest_file(path, size):
    before = _regular(path, size)
    if before.st_size != size:
        raise ValueError("Output size mismatch")
    digest = hashlib.sha256()
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        if _identity(os.fstat(fd)) != _identity(before):
            raise ValueError("Output changed before hash")
        left = size
        while left:
            block = stream.read(min(left, 1024 * 1024))
            if not block:
                raise ValueError("Output shrank")
            digest.update(block)
            left -= len(block)
        if stream.read(1) or _identity(os.fstat(fd)) != _identity(before):
            raise ValueError("Output changed during hash")
    return digest.hexdigest()


def _files(items, cap=MAX_BYTES):
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_FILES:
        raise ValueError("Invalid file count")
    names = set()
    total = 0
    for item in items:
        if not isinstance(item, dict) or set(item) != {"name", "bytes", "sha256"}:
            raise ValueError("Invalid file entry")
        name, size, digest = item["name"], item["bytes"], item["sha256"]
        if (not isinstance(name, str) or not NAME.fullmatch(name) or name in names or
            type(size) is not int or size < 0 or size > cap or
            not isinstance(digest, str) or not HEX.fullmatch(digest)):
            raise ValueError("Invalid output identity")
        names.add(name)
        total += size
        if total > cap:
            raise ValueError("Output byte budget exceeded")
    return names, total


def _verify_copy(copy_dir, entries):
    directory = Path(copy_dir)
    if (not stat.S_ISDIR(directory.lstat().st_mode) or
        directory.stat().st_mode & 0o222 or
        {p.name for p in directory.iterdir()} != {item["name"] for item in entries}):
        raise ValueError("Raw COPY directory identity/read-only state mismatch")
    records = {}
    source_count = 0
    source_counts = {kind: 0 for kind in COUNTS}
    for item in entries:
        path = directory / item["name"]
        before = _regular(path, MAX_SOURCE_BYTES)
        if before.st_mode & 0o222 or before.st_size != item["bytes"]:
            raise ValueError("Raw COPY file size/read-only state mismatch")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            if _identity(os.fstat(fd)) != _identity(before):
                raise ValueError("Raw COPY changed before scan")
            digest = hashlib.sha256()
            left = before.st_size
            while left:
                offset = stream.tell()
                raw = stream.readline(min(MAX_RECORD_BYTES + 1, left))
                if not raw or len(raw) > MAX_RECORD_BYTES or not raw.endswith(b"\n"):
                    raise ValueError("Invalid raw COPY record")
                left -= len(raw)
                digest.update(raw)
                event = json.loads(raw, object_pairs_hook=_unique, parse_constant=_constant)
                quality = event.get("data_quality")
                if isinstance(quality, dict) and quality.get("collector_session_id") == SID:
                    seq = quality.get("ingest_sequence")
                    if type(seq) is not int or seq < 1 or seq in records:
                        raise ValueError("Invalid source-session sequence")
                    kind = event.get("event_type")
                    if kind not in source_counts:
                        raise ValueError("Invalid source-session event type")
                    source_counts[kind] += 1
                    source_count += 1
                    if seq <= MAX_RECORDS + 1:
                        records[seq] = (path, offset, len(raw), event.get("event_type"),
                                        before, quality.get("applied_ts"))
            if digest.hexdigest() != item["sha256"] or _identity(os.fstat(fd)) != _identity(before):
                raise ValueError("Raw COPY SHA-256/identity mismatch")
    return records, source_count, source_counts


def _verify_prefix(records, source_count, selected, files, prefix, scope, total):
    from contextlib import ExitStack
    observed = {kind: 0 for kind in COUNTS}
    with ExitStack() as stack:
        outputs = {item["name"]: stack.enter_context((prefix / item["name"]).open("rb"))
                   for item in files}
        sources = {}
        identities = {}
        for path, _, _, _, before, _ in records.values():
            if path not in sources:
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                sources[path] = stack.enter_context(os.fdopen(fd, "rb"))
                identities[path] = _identity(before)
                if _identity(os.fstat(fd)) != _identity(before):
                    raise ValueError("Raw COPY changed before prefix comparison")
        used = 0
        first_at = last_at = None
        for seq in range(1, selected + 1):
            if seq not in records:
                raise ValueError("Missing source-session prefix sequence")
            path, offset, length, kind, _, applied_at = records[seq]
            source = sources[path]
            source.seek(offset)
            raw = source.read(length)
            output = outputs.get(path.name)
            if (output is None or output.read(length) != raw or len(raw) != length or
                kind not in observed):
                raise ValueError("Output differs from exact source-session prefix bytes")
            used += length
            observed[kind] += 1
            if not isinstance(applied_at, str) or len(applied_at) > 40:
                raise ValueError("Missing source applied timestamp")
            at = datetime.fromisoformat(applied_at.replace("Z", "+00:00"))
            if at.tzinfo is None or at.utcoffset() != timedelta(0):
                raise ValueError("Source applied timestamp must be UTC")
            at = at.astimezone(timezone.utc)
            first_at = at if first_at is None else first_at
            last_at = at
        if any(stream.read(1) for stream in outputs.values()) or used != total:
            raise ValueError("Output has trailing bytes or incorrect serialized size")
        for path, source in sources.items():
            if _identity(os.fstat(source.fileno())) != identities[path]:
                raise ValueError("Raw COPY changed during prefix comparison")
    if source_count == selected:
        expected_scope = "source_end"
    elif selected == MAX_RECORDS:
        expected_scope = "record_limit"
    else:
        following = records.get(selected + 1)
        if following is None or used + following[2] <= MAX_BYTES:
            raise ValueError("Incomplete prefix without byte limit")
        expected_scope = "byte_limit"
    if scope != expected_scope:
        raise ValueError("Truncation scope disagrees with source-session prefix")
    return observed, first_at, last_at


def validate(output, source_manifest, spec, raw_copy_dir, *, expected_source_counts=COUNTS):
    # The CLI never exposes this synthetic-fixture override; production is pinned.
    if (not isinstance(expected_source_counts, dict) or set(expected_source_counts) != set(COUNTS)
        or any(type(value) is not int or value < 0 for value in expected_source_counts.values())):
        raise ValueError("Invalid source-session count expectation")
    if hashlib.sha256(_read(Path(spec), METADATA_CAP)).hexdigest() != SPEC_SHA:
        raise ValueError("Pinned research-input-v1 specification changed")
    source = _json(Path(source_manifest), METADATA_CAP)
    if (not isinstance(source, dict) or source.get("manifest_version") != "completed-raw-copy-v1" or
        source.get("completed") is not True or source.get("session_id") != SID or
        source.get("expected_counts") != COUNTS or source.get("expected_feature_sha256") != FEATURE_SHA):
        raise ValueError("Completed source identity mismatch")
    source_names, _ = _files(source.get("files"), MAX_SOURCE_BYTES)
    if (len(source_names) != 4 or
        not any("_depth_" in name for name in source_names) or
        not any("_trade_" in name for name in source_names)):
        raise ValueError("Exactly four source files across both streams required")
    records, source_count, source_counts = _verify_copy(raw_copy_dir, source["files"])
    if source_counts != expected_source_counts:
        raise ValueError("Raw COPY source-session counts disagree with expectation")
    parent = Path(output)
    prefix = parent / "prefix"
    if not stat.S_ISDIR(parent.lstat().st_mode) or not stat.S_ISDIR(prefix.lstat().st_mode):
        raise ValueError("Output/prefix must be real directories")
    if {p.name for p in parent.iterdir()} != {"prefix"}:
        raise ValueError("Unexpected top-level output")
    extraction = _json(prefix / "extraction-v1.json", OUTPUT_METADATA_CAP)
    runner = _json(prefix / "research-input-v1.json", OUTPUT_METADATA_CAP)
    if not isinstance(extraction, dict) or not isinstance(runner, dict):
        raise ValueError("Invalid output manifests")
    if (extraction.get("manifest_version") != "research-extraction-v1" or
        extraction.get("status") != "complete_prefix" or
        extraction.get("source_session_id") != SID or
        extraction.get("source_manifest_sha256") != hashlib.sha256(_canonical(source)).hexdigest() or
        extraction.get("source_files") != sorted(source["files"], key=lambda f: f["name"]) or
        extraction.get("source_expected_counts") != COUNTS or
        extraction.get("source_verified_counts") != COUNTS or
        extraction.get("source_capture_hashes_verified") != sum(COUNTS.values()) or
        extraction.get("source_verified_feature_sha256") != FEATURE_SHA):
        raise ValueError("Extraction source verification mismatch")
    policy = extraction.get("selection_policy")
    if policy != {"start_ingest_sequence": 1, "max_records": MAX_RECORDS,
                  "max_serialized_raw_bytes": MAX_BYTES, "stop_before_exceeding_either_limit": True}:
        raise ValueError("Prefix selection policy mismatch")
    selected = extraction.get("selected_records")
    counts = extraction.get("selected_counts")
    if (type(selected) is not int or not 1 <= selected <= MAX_RECORDS or
        not isinstance(counts, dict) or set(counts) != set(COUNTS) or
        any(type(v) is not int or v < 0 or v > COUNTS[k] for k, v in counts.items()) or
        counts["book_snapshot"] != 1 or sum(counts.values()) != selected or
        extraction.get("first_ingest_sequence") != 1 or
        extraction.get("last_ingest_sequence") != selected):
        raise ValueError("Selected record counts/sequence mismatch")
    try:
        first = datetime.fromisoformat(extraction["first_applied_ts"])
        last = datetime.fromisoformat(extraction["last_applied_ts"])
        duration = extraction["usable_duration_seconds"]
        if (first.utcoffset() != timedelta(0) or last.utcoffset() != timedelta(0) or
            type(duration) not in (int, float) or not math.isfinite(duration) or
            duration < 0 or abs((last - first).total_seconds() - duration) > 0.000001 or
            extraction["usable_duration_status"] != (
                "insufficient_for_proposed_60_day_split" if duration < 60 * 86400
                else "duration_only_not_split_approved") or
            extraction["truncation_scope"] not in ("source_end", "record_limit", "byte_limit") or
            extraction["scope"] != SCOPE):
            raise ValueError("Invalid prefix duration, truncation or scope")
    except (KeyError, TypeError, OverflowError) as exc:
        raise ValueError("Missing or invalid prefix duration/scope") from exc
    files = extraction.get("output_files")
    names, total = _files(files)
    assert isinstance(files, list)  # _files validated the type and entries.
    if (not names <= source_names or extraction.get("serialized_raw_bytes") != total or
        runner.get("manifest_version") != "research-input-v1" or
        runner.get("session_id") != SID or runner.get("spec_sha256") != SPEC_SHA or
        runner.get("expected_counts") != counts or runner.get("files") != files):
        raise ValueError("Research input manifest or output bytes mismatch")
    allowed = names | {"extraction-v1.json", "research-input-v1.json",
                       ".extraction-v1.json.incomplete", ".research-input-v1.json.incomplete"}
    actual = {p.name for p in prefix.iterdir()}
    if not names | {"extraction-v1.json", "research-input-v1.json"} <= actual or actual - allowed:
        raise ValueError("Unexpected/missing prefix files")
    for name in actual:
        if name.startswith("."):
            _regular(prefix / name, OUTPUT_METADATA_CAP)
    for item in files:
        if _digest_file(prefix / item["name"], item["bytes"]) != item["sha256"]:
            raise ValueError("Output SHA-256 mismatch")
    observed, source_first, source_last = _verify_prefix(
        records, source_count, selected, files, prefix, extraction["truncation_scope"], total)
    if (observed != counts or source_first != first or source_last != last):
        raise ValueError("Serialized prefix counts/timestamps disagree with manifests")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["validate"])
    parser.add_argument("--output", required=True)
    parser.add_argument("--source-manifest", required=True)
    parser.add_argument("--raw-copy-dir", required=True)
    parser.add_argument("--spec", required=True)
    args = parser.parse_args()
    try:
        validate(args.output, args.source_manifest, args.spec, args.raw_copy_dir)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Research output validation failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
