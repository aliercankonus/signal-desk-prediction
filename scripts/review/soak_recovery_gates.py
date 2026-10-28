#!/usr/bin/env python3
"""Read-only recovery diagnostics for one existing interrupted soak session."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

from acceptance_gates import verify_raw_prefix
from soak_gates import (MAX_RECORD, RAW, SHA, SID, append_counts,
                        positive, save_exclusive, verify_raw_set, verify_session)

TARGET_SID = "cb8a0767d7284b8aaa3d09fbca7095f2"
MAX_METADATA_BYTES = 4 * 1024 * 1024
MAX_RAW_FILES = 64
MAX_RAW_FILE_BYTES = 8 * 1024 * 1024 * 1024


def stable_identity(info):
    # Reads may update atime; that is not a data mutation.
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def hash_regular(path, cap):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as source:
        before = os.fstat(source.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > cap:
            raise ValueError("Unsupported file type or size cap exceeded")
        remaining = before.st_size
        digest = hashlib.sha256()
        while remaining:
            chunk = source.read(min(1024 * 1024, remaining))
            if not chunk:
                raise ValueError("File shrank during bounded hash")
            digest.update(chunk)
            remaining -= len(chunk)
        if stable_identity(before) != stable_identity(os.fstat(source.fileno())):
            raise ValueError("File changed during bounded hash")
        return digest.hexdigest()


def save_manifest(path, entries):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        for source, digest in entries:
            output.write(f"{digest}  {source}\n")


def freeze_raw(raw_dir, output):
    raw_dir = Path(raw_dir)
    files = sorted(p for p in raw_dir.iterdir() if p.suffix == ".jsonl")
    if not 1 <= len(files) <= MAX_RAW_FILES or any(not RAW.fullmatch(p.name) for p in files):
        raise ValueError("Missing or oversized raw file set")
    entries = [(p, hash_regular(p, MAX_RAW_FILE_BYTES)) for p in files]
    verify_raw_set(raw_dir, {p.name: digest for p, digest in entries})
    save_manifest(output, entries)


def freeze_original(original, output):
    original = Path(original)
    files = sorted(original.iterdir())
    if not 1 <= len(files) <= 128 or any(not re.fullmatch(r"[A-Za-z0-9._-]+", p.name) for p in files):
        raise ValueError("Missing or oversized original evidence file set")
    entries = [(p, hash_regular(p, 512 * 1024 * 1024)) for p in files]
    if {p.name for p in original.iterdir()} != {p.name for p, _ in entries}:
        raise ValueError("Original evidence file set changed")
    save_manifest(output, entries)


def load_bounded(path):
    with Path(path).open("rb") as source:
        content = source.read(MAX_METADATA_BYTES + 1)
    if len(content) > MAX_METADATA_BYTES:
        raise ValueError("Recovery metadata byte cap exceeded")
    return json.loads(content)


def manifest_lines(path):
    with Path(path).open("rb") as source:
        content = source.read(MAX_METADATA_BYTES + 1)
    if len(content) > MAX_METADATA_BYTES:
        raise ValueError("Recovery manifest byte cap exceeded")
    if not content.endswith(b"\n"):
        raise ValueError("Incomplete recovery manifest")
    return content.decode("utf-8").splitlines()


def parse_raw_manifest(path, raw_dir):
    result = {}
    for line in manifest_lines(path):
        if len(line) < 67 or not SHA.fullmatch(line[:64]) or line[64:66] != "  ":
            raise ValueError("Malformed raw hash manifest")
        name = Path(line[66:]).name
        if (not RAW.fullmatch(name) or line[66:] != str(Path(raw_dir) / name)
                or name in result):
            raise ValueError("Unexpected raw manifest path")
        result[name] = line[:64]
    if not 1 <= len(result) <= MAX_RAW_FILES:
        raise ValueError("Missing or oversized raw manifest")
    return result


def verify_original_evidence(original, manifest):
    """Verify every original file, including the exact original file set."""
    original = Path(original)
    entries = {}
    for line in manifest_lines(manifest):
        if len(line) < 67 or not SHA.fullmatch(line[:64]) or line[64:66] != "  ":
            raise ValueError("Malformed original evidence manifest")
        name = Path(line[66:]).name
        if (not re.fullmatch(r"[A-Za-z0-9._-]+", name) or
            line[66:] != str(original / name) or name in entries):
            raise ValueError("Unexpected original evidence path")
        entries[name] = line[:64]
    if not 1 <= len(entries) <= 128 or {p.name for p in original.iterdir()} != set(entries):
        raise ValueError("Original evidence file set changed")
    for name, wanted in sorted(entries.items()):
        if hash_regular(original / name, 512 * 1024 * 1024) != wanted:
            raise ValueError("Original evidence file changed")
    if {p.name for p in original.iterdir()} != set(entries):
        raise ValueError("Original evidence file set changed")


def check_aggregate_limit(raw_dir, pre, limit=2_000_000):
    """Cap ALL appended records before the per-session ordering scan."""
    count = 0
    for path in sorted(Path(raw_dir).glob("*.jsonl")):
        offset = pre["files"].get(path.name, {"size": 0}).get("size")
        if type(offset) is not int or offset < 0:
            raise ValueError("Invalid original raw byte offset")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as source:
            before = os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_RAW_FILE_BYTES or before.st_size < offset:
                raise ValueError("Unbounded or changed raw file")
            source.seek(offset)
            remaining = before.st_size - offset
            while remaining:
                line = source.readline(min(MAX_RECORD + 1, remaining))
                if not line or len(line) > MAX_RECORD or not line.endswith(b"\n"):
                    raise ValueError("Incomplete or oversized appended record")
                remaining -= len(line)
                count += 1
                if count > limit:
                    raise ValueError("aggregate record cap exceeded")
            if stable_identity(before) != stable_identity(os.fstat(source.fileno())):
                raise ValueError("Raw file changed during aggregate count")
    return count


def derive(raw_dir, pre, session_id):
    """Verify old byte prefixes, then count only existing appended session records."""
    if session_id != TARGET_SID or not SID.fullmatch(session_id):
        raise ValueError("Unreviewed recovery session ID")
    if not isinstance(pre, dict) or not isinstance(pre.get("files"), dict) or not 1 <= len(pre["files"]) <= MAX_RAW_FILES:
        raise ValueError("Missing or oversized original raw inventory")
    for name, previous in pre["files"].items():
        if (not isinstance(name, str) or name in ("", ".", "..") or
            Path(name).name != name or "\x00" in name or not isinstance(previous, dict) or
            type(previous.get("size")) is not int or not 0 <= previous["size"] <= MAX_RAW_FILE_BYTES):
            raise ValueError("Original raw inventory size cap or name invalid")
        info = (Path(raw_dir) / name).lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_RAW_FILE_BYTES:
            raise ValueError("Original raw inventory size cap or file type invalid")
    names = []
    with os.scandir(raw_dir) as entries:
        for entry in entries:
            if not entry.name.endswith(".jsonl"):
                continue
            names.append(entry.name)
            if len(names) > MAX_RAW_FILES:
                raise ValueError("Existing raw file cap exceeded")
            info = entry.stat(follow_symlinks=False)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_RAW_FILE_BYTES:
                raise ValueError("Existing raw file type or size cap exceeded")
    if not names or any(not RAW.fullmatch(name) for name in names):
        raise ValueError("Missing or unrecognized existing raw file")
    verify_raw_prefix(Path(raw_dir), pre)
    aggregate = check_aggregate_limit(raw_dir, pre)
    sessions = append_counts(raw_dir, pre)
    if len(sessions) != 1 or sessions[0].get("session_id") != session_id:
        raise ValueError("Existing appended data is not exactly the pinned session")
    item = sessions[0]
    if (item["book_snapshot"] != 1 or not positive(item["book_delta"]) or
            not positive(item["trade"]) or item["records"] != aggregate):
        raise ValueError("Incomplete or unbounded existing session counts")
    return {"session_id": session_id,
            "counts": {key: item[key] for key in ("book_snapshot", "book_delta", "trade")},
            "records": item["records"],
            "counts_origin": "raw_appended_bytes_not_independent_completion_evidence",
            "independent_completion_verified": False, "soak_acceptance": False}


def compare_operator_counts(derived, reported):
    """Gate audit/replay on totals supplied apart from raw-data derivation."""
    keys = {"book_snapshot", "book_delta", "trade", "records"}
    if (not isinstance(derived, dict) or derived.get("session_id") != TARGET_SID or
        not isinstance(reported, dict) or set(reported) != keys or
        any(type(value) is not int or value <= 0 for value in reported.values()) or
        reported["book_snapshot"] != 1):
        raise ValueError("Invalid operator-reported collector totals")
    if sum(reported[name] for name in ("book_snapshot", "book_delta", "trade")) != reported["records"]:
        raise ValueError("inconsistent operator-reported total")
    if derived.get("counts") != {name: reported[name] for name in ("book_snapshot", "book_delta", "trade")} or derived.get("records") != reported["records"]:
        raise ValueError("operator-reported counts mismatch raw-derived counts")
    return {"session_id": TARGET_SID, "operator_reported_collector_totals": reported,
            "provenance": "operator_report_not_direct_host_inspection",
            "raw_derived_counts_match": True, "independent_completion_verified": False,
            "resource_sampling_complete": False, "soak_acceptance": False}


def approve_current_baseline(approval_digest, declaration):
    """Record an operator-approved CURRENT baseline, not a historical digest."""
    if not isinstance(approval_digest, str) or not SHA.fullmatch(approval_digest):
        raise ValueError("Invalid current candidate approval digest")
    if declaration != "operator-approved-current-recovery-baseline":
        raise ValueError("Explicit current-only operator approval required")
    return {"provenance": "operator_approved_current_recovery_baseline",
            "candidate_approval_sha256": approval_digest,
            "historical_approval_unchanged_verified": False,
            "resource_sampling_complete": False, "soak_acceptance": False}


def verify_current_raw(raw_dir, manifest):
    if not isinstance(manifest, dict) or not 1 <= len(manifest) <= MAX_RAW_FILES:
        raise ValueError("Missing or oversized frozen raw manifest")
    if any(not isinstance(name, str) or not RAW.fullmatch(name) or
           not isinstance(digest, str) or not SHA.fullmatch(digest)
           for name, digest in manifest.items()):
        raise ValueError("Invalid frozen raw manifest")
    verify_raw_set(raw_dir, manifest)
    for name, wanted in sorted(manifest.items()):
        if hash_regular(Path(raw_dir) / name, MAX_RAW_FILE_BYTES) != wanted:
            raise ValueError("Frozen raw file changed or hash mismatch")
    verify_raw_set(raw_dir, manifest)


def verify(derived, audit, replays, manifest, raw_dir, comparison, baseline):
    """Compare completed diagnostics; never declare a recovered soak success."""
    if (not isinstance(derived, dict) or derived.get("session_id") != TARGET_SID or
        derived.get("counts_origin") != "raw_appended_bytes_not_independent_completion_evidence" or
        derived.get("soak_acceptance") is not False or
        derived.get("independent_completion_verified") is not False):
        raise ValueError("Invalid recovery provenance")
    counts = derived.get("counts")
    if (not isinstance(counts, dict) or set(counts) != {"book_snapshot", "book_delta", "trade"} or
        any(type(n) is not int for n in counts.values()) or
        derived.get("records") != sum(counts.values())):
        raise ValueError("Invalid derived recovery counts")
    if not isinstance(comparison, dict):
        raise ValueError("Invalid operator counts provenance")
    try:
        checked_comparison = compare_operator_counts(derived, comparison.get("operator_reported_collector_totals"))
    except ValueError as exc:
        raise ValueError("Invalid operator counts provenance") from exc
    if comparison != checked_comparison:
        raise ValueError("Invalid operator counts provenance")
    if not isinstance(baseline, dict):
        raise ValueError("Invalid current baseline provenance")
    try:
        checked_baseline = approve_current_baseline(
            baseline.get("candidate_approval_sha256"), "operator-approved-current-recovery-baseline")
    except ValueError as exc:
        raise ValueError("Invalid current baseline provenance") from exc
    if baseline != checked_baseline:
        raise ValueError("Invalid current baseline provenance")
    verify_current_raw(raw_dir, manifest)
    expected = {"session_id": TARGET_SID, **counts, "records": derived["records"]}
    result = verify_session(expected, audit, replays, manifest)
    verify_current_raw(raw_dir, manifest)
    return {"diagnostic_status": "stored_session_audit_replay_matched",
            "session_id": TARGET_SID, "records": derived["records"],
            "feature_sha256": result["feature_sha256"],
            "ready_features": result["ready_features"],
            "files_checked": result["files_checked"],
            "counts_origin": derived["counts_origin"],
            "operator_reported_collector_totals": comparison["operator_reported_collector_totals"],
            "operator_counts_provenance": comparison["provenance"],
            "approval_provenance": baseline["provenance"],
            "candidate_approval_sha256": baseline["candidate_approval_sha256"],
            "historical_approval_unchanged_verified": False,
            "resource_sampling_complete": False,
            "independent_completion_verified": False, "soak_acceptance": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    first = sub.add_parser("derive")
    for name in ("raw-dir", "pre-inventory", "session-id", "output"):
        first.add_argument("--" + name, required=True)
    counts = sub.add_parser("compare-counts")
    counts.add_argument("--summary", required=True)
    for name in ("expected-snapshots", "expected-depth", "expected-trades", "expected-total"):
        counts.add_argument("--" + name, required=True, type=int)
    counts.add_argument("--output", required=True)
    baseline = sub.add_parser("record-baseline")
    for name in ("approval-sha256", "approval-declaration", "output"):
        baseline.add_argument("--" + name, required=True)
    final = sub.add_parser("verify")
    for name in ("raw-dir", "summary", "audit", "replay-one", "replay-two", "manifest",
                 "operator-counts", "baseline", "output"):
        final.add_argument("--" + name, required=True)
    original = sub.add_parser("verify-original")
    original.add_argument("--original", required=True)
    original.add_argument("--manifest", required=True)
    for command, source in (("freeze-raw", "raw-dir"), ("freeze-original", "original")):
        freezer = sub.add_parser(command)
        freezer.add_argument("--" + source, required=True)
        freezer.add_argument("--output", required=True)
    raw_check = sub.add_parser("verify-raw")
    raw_check.add_argument("--raw-dir", required=True)
    raw_check.add_argument("--manifest", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.command == "derive":
            result = derive(args.raw_dir, load_bounded(args.pre_inventory), args.session_id)
        elif args.command == "compare-counts":
            reported = {"book_snapshot": args.expected_snapshots, "book_delta": args.expected_depth,
                        "trade": args.expected_trades, "records": args.expected_total}
            result = compare_operator_counts(load_bounded(args.summary), reported)
        elif args.command == "record-baseline":
            result = approve_current_baseline(args.approval_sha256, args.approval_declaration)
        elif args.command == "verify":
            result = verify(load_bounded(args.summary), load_bounded(args.audit),
                            [load_bounded(args.replay_one), load_bounded(args.replay_two)],
                            parse_raw_manifest(args.manifest, args.raw_dir), args.raw_dir,
                            load_bounded(args.operator_counts), load_bounded(args.baseline))
        elif args.command == "freeze-raw":
            freeze_raw(args.raw_dir, args.output)
            return 0
        elif args.command == "freeze-original":
            freeze_original(args.original, args.output)
            return 0
        elif args.command == "verify-raw":
            verify_current_raw(args.raw_dir, parse_raw_manifest(args.manifest, args.raw_dir))
            return 0
        else:
            verify_original_evidence(args.original, args.manifest)
            return 0
        save_exclusive(args.output, result)
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Recovery diagnostics failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
