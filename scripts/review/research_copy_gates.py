#!/usr/bin/env python3
"""Offline recovery evidence gate and byte-verified, read-only research COPY.

The completed manifest describes completion of the COPY transaction, not acceptance
of the interrupted collector soak. Python-only expected-value overrides are for
synthetic fixtures; the CLI always pins production identity, counts and digest.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import stat
import sys
import threading
import time
import uuid
from functools import wraps

from soak_gates import RAW, SHA
from soak_recovery_gates import (TARGET_SID, derive, load_bounded, parse_raw_manifest,
                                 verify_original_evidence, verify as verify_recovery)

COUNTS = {"book_snapshot": 1, "book_delta": 35936, "trade": 222238}
DIGEST = "bafabf00f920c948a7f952425d105197039af0104c0b28b65904afdbe94bf6c0"
TOTAL = 258175
READY_FEATURES = 258114
SOURCE_CAP = 768 * 1024 * 1024
FILE_COUNT = 4
TIME_CAP = 1800
CHUNK = 1024 * 1024


def _hard_limit(operation):
    """Interrupt bounded upstream recovery scans as well as our own read loops."""
    @wraps(operation)
    def run(*args, **kwargs):
        seconds = kwargs.get("max_runtime_seconds", TIME_CAP)
        if (not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or
            not 0 < seconds <= TIME_CAP or threading.current_thread() is not threading.main_thread()):
            raise ValueError("Invalid runtime cap or non-main-thread verification")
        previous_handler = signal.getsignal(signal.SIGALRM)
        previous_timer = signal.getitimer(signal.ITIMER_REAL)
        def expired(*_):
            raise ValueError("Verification runtime budget exhausted")
        signal.signal(signal.SIGALRM, expired)
        signal.setitimer(signal.ITIMER_REAL, seconds)
        try:
            return operation(*args, **kwargs)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)
            if previous_timer[0] > 0:
                signal.setitimer(signal.ITIMER_REAL, *previous_timer)
    return run


def _directory(path):
    p = Path(path).absolute()
    if not p.is_dir() or p.resolve(strict=True) != p:
        raise ValueError("Directory missing, noncanonical or symlinked")
    return p


def _path(path):
    p = Path(path).absolute()
    if p.parent.resolve(strict=True) != p.parent:
        raise ValueError("Output parent linked")
    if p.exists() or p.is_symlink():
        raise FileExistsError("Output already exists")
    return p


def _outside(path, protected):
    if any(path == p or path.is_relative_to(p) or p.is_relative_to(path) for p in protected):
        raise ValueError("COPY/output overlaps protected raw or evidence")


def _deadline(deadline):
    if time.monotonic() > deadline:
        raise ValueError("Verification runtime budget exhausted")


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _read_source(path, cap, deadline, destination=None):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as source:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > cap:
            raise ValueError("Source is non-regular or exceeds byte budget")
        remaining = before.st_size
        digest = hashlib.sha256()
        lines = 0
        last = b""
        while remaining:
            _deadline(deadline)
            chunk = source.read(min(CHUNK, remaining))
            if not chunk:
                raise ValueError("Source shrank during bounded read")
            digest.update(chunk)
            lines += chunk.count(b"\n")
            last = chunk[-1:]
            if destination is not None:
                destination.write(chunk)
            remaining -= len(chunk)
        if _identity(os.fstat(fd)) != _identity(before):
            raise ValueError("Source changed during bounded read")
        if before.st_size and last != b"\n":
            raise ValueError("Incomplete raw record")
        return {"bytes": before.st_size, "sha256": digest.hexdigest(), "lines": lines}


def _raw_inventory(directory, deadline):
    entries = []
    with os.scandir(directory) as stream:
        for entry in stream:
            entries.append(directory / entry.name)
            if len(entries) > FILE_COUNT:
                raise ValueError("Exactly four recognized raw files required")
    entries.sort()
    if len(entries) != FILE_COUNT or any(not RAW.fullmatch(p.name) for p in entries):
        raise ValueError("Exactly four recognized raw files required")
    if {"depth", "trade"} != {"depth" if "_depth_" in p.name else "trade" for p in entries}:
        raise ValueError("Both raw streams required")
    sizes = [os.stat(p, follow_symlinks=False) for p in entries]
    if any(not stat.S_ISREG(info.st_mode) for info in sizes) or sum(info.st_size for info in sizes) > SOURCE_CAP:
        raise ValueError("Source is non-regular or exceeds byte budget")
    files = {}
    remaining = SOURCE_CAP
    for p in entries:
        _deadline(deadline)
        item = _read_source(p, remaining, deadline)
        remaining -= item["bytes"]
        files[p.name] = item
    names = set()
    with os.scandir(directory) as stream:
        for entry in stream:
            names.add(entry.name)
            if len(names) > FILE_COUNT:
                raise ValueError("Raw file set changed")
    if names != set(files):
        raise ValueError("Raw file set changed")
    return files


def _publish(path, value):
    """Publish a complete JSON file with exclusive link; never expose partial JSON."""
    path = _path(path)
    temporary = path.parent / ("." + path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(value, out, sort_keys=True)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        temporary_info = os.stat(temporary, follow_symlinks=False)
        try:
            os.link(temporary, path, follow_symlinks=False)
            dirfd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                os.fsync(dirfd)
            finally:
                os.close(dirfd)
        except BaseException:
            try:
                published_info = os.stat(path, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                if (published_info.st_dev, published_info.st_ino) == (temporary_info.st_dev, temporary_info.st_ino):
                    path.unlink()
            raise
    finally:
        temporary.unlink(missing_ok=True)


def _evaluate(recovery, original, raw, expected_session_id, expected_counts,
              expected_feature_sha256, expected_ready_features, expected_approval_sha256, deadline):
    if (not isinstance(expected_session_id, str) or expected_session_id != TARGET_SID or
        not isinstance(expected_counts, dict) or set(expected_counts) != set(COUNTS) or
        expected_counts["book_snapshot"] != 1 or
        any(type(n) is not int or n <= 0 for n in expected_counts.values()) or
        not isinstance(expected_feature_sha256, str) or not SHA.fullmatch(expected_feature_sha256) or
        type(expected_ready_features) is not int or expected_ready_features < 0 or
        not isinstance(expected_approval_sha256, str) or not SHA.fullmatch(expected_approval_sha256)):
        raise ValueError("Invalid expected source identity")
    recovery, original, raw = map(_directory, (recovery, original, raw))
    if any(a == b or a.is_relative_to(b) or b.is_relative_to(a)
           for a, b in ((recovery, original), (recovery, raw), (original, raw))):
        raise ValueError("Overlapping original, recovery, raw directories")
    verify_original_evidence(original, recovery / "original-evidence.sha256")
    pre = load_bounded(original / "raw-pre-capture.json")
    if not isinstance(pre, dict) or not isinstance(pre.get("files"), dict):
        raise ValueError("Missing original raw inventory")
    _deadline(deadline)
    frozen = parse_raw_manifest(recovery / "raw-before.sha256", raw)
    actual = _raw_inventory(raw, deadline)
    if set(frozen) != set(actual) or any(frozen[name] != item["sha256"] for name, item in actual.items()):
        raise ValueError("Frozen source SHA-256 mismatch")
    derived = load_bounded(recovery / "derived-counts.json")
    if derived != derive(raw, pre, expected_session_id):
        raise ValueError("Derived recovery counts do not match source raw bytes")
    _deadline(deadline)
    comparison = load_bounded(recovery / "operator-counts-compared.json")
    baseline = load_bounded(recovery / "current-recovery-baseline.json")
    audit = load_bounded(recovery / "audit.json")
    replays = [load_bounded(recovery / f"replay-{n}.json") for n in (1, 2)]
    diagnostic = load_bounded(recovery / "diagnostics.json")
    if (derived.get("session_id") != expected_session_id or
        derived.get("counts") != expected_counts or
        derived.get("records") != sum(expected_counts.values()) or
        comparison.get("operator_reported_collector_totals") !=
            {**expected_counts, "records": sum(expected_counts.values())}):
        raise ValueError("Pinned collector counts mismatch")
    # The recovery gate validates counts, provenance and matching replay signatures.
    checked = verify_recovery(derived, audit, replays, frozen, raw, comparison, baseline)
    if baseline["candidate_approval_sha256"] != expected_approval_sha256:
        raise ValueError("Operator-approved current approval digest mismatch")
    if (diagnostic != checked or checked["files_checked"] != FILE_COUNT or
        checked["feature_sha256"] != expected_feature_sha256 or
        checked["ready_features"] != [expected_ready_features, expected_ready_features] or
        checked["soak_acceptance"] is not False or
        checked["independent_completion_verified"] is not False):
        raise ValueError("Recovery diagnostic, ready count or ordered digest mismatch")
    for record in (audit, *replays):
        if {f["file"] for f in record["files"]} != set(actual):
            raise ValueError("Incomplete audit/replay file set")
        for f in record["files"]:
            observed = actual[f["file"]]
            if (type(f["bytes"]) is not int or type(f["lines"]) is not int or
                f["bytes"] != observed["bytes"] or f["lines"] != observed["lines"] or
                f["sha256"] != observed["sha256"]):
                raise ValueError("Audit/replay byte, line or digest mismatch")
    _deadline(deadline)
    return {"verified_source_version": "recovery-verified-source-v1",
            "session_id": expected_session_id, "expected_counts": expected_counts,
            "expected_feature_sha256": expected_feature_sha256,
            "expected_ready_features": expected_ready_features,
            "expected_approval_sha256": expected_approval_sha256,
            "raw_dir": str(raw), "original_dir": str(original),
            "recovery_dir": str(recovery),
            "source_files": [{"name": name, "bytes": item["bytes"],
                              "sha256": item["sha256"]} for name, item in actual.items()],
            "operator_counts_provenance": checked["operator_counts_provenance"],
            "source_session_completion_provenance": "operator_report_not_direct_host_inspection",
            "independent_completion_verified": False, "soak_acceptance": False}


@_hard_limit
def verify_evidence(recovery, original, raw_dir, output, *,
                    expected_session_id=TARGET_SID, expected_counts=None,
                    expected_feature_sha256=DIGEST, expected_ready_features=READY_FEATURES,
                    expected_approval_sha256, max_runtime_seconds=TIME_CAP):
    if expected_counts is None:
        expected_counts = COUNTS
    if not isinstance(max_runtime_seconds, (int, float)) or not math.isfinite(max_runtime_seconds) or not 0 < max_runtime_seconds <= TIME_CAP:
        raise ValueError("Invalid runtime cap")
    out = _path(output)
    raw, orig, rec = map(_directory, (raw_dir, original, recovery))
    _outside(out, (raw, orig, rec))
    result = _evaluate(rec, orig, raw, expected_session_id, expected_counts,
                       expected_feature_sha256, expected_ready_features, expected_approval_sha256,
                       time.monotonic() + max_runtime_seconds)
    _publish(out, result)
    return result


@_hard_limit
def copy_verified(verified, raw_dir, copy_dir, manifest_out, *, max_runtime_seconds=TIME_CAP):
    if not isinstance(max_runtime_seconds, (int, float)) or not math.isfinite(max_runtime_seconds) or not 0 < max_runtime_seconds <= TIME_CAP:
        raise ValueError("Invalid runtime cap")
    deadline = time.monotonic() + max_runtime_seconds
    source = _directory(raw_dir)
    metadata = load_bounded(verified)
    if not isinstance(metadata, dict) or metadata.get("verified_source_version") != "recovery-verified-source-v1" or metadata.get("raw_dir") != str(source):
        raise ValueError("Untrusted verified-source metadata")
    original = _directory(metadata["original_dir"])
    recovery = _directory(metadata["recovery_dir"])
    verified_file = Path(verified).absolute()
    if verified_file.resolve(strict=True) != verified_file or verified_file.is_symlink():
        raise ValueError("Linked verified-source metadata")
    destination = _path(copy_dir)
    manifest_path = _path(manifest_out)
    _outside(destination, (source, original, recovery))
    _outside(manifest_path, (source, original, recovery, destination))
    if destination == manifest_path or manifest_path.is_relative_to(destination):
        raise ValueError("Manifest must be outside COPY directory")
    checked = _evaluate(recovery, original, source, metadata["session_id"],
                        metadata["expected_counts"], metadata["expected_feature_sha256"],
                        metadata["expected_ready_features"], metadata["expected_approval_sha256"], deadline)
    if checked != metadata:
        raise ValueError("Verified-source metadata does not match current evidence")
    destination.mkdir(mode=0o700)
    items = checked["source_files"]
    for item in items:
        _deadline(deadline)
        path = destination / item["name"]
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as out:
            observed = _read_source(source / item["name"], item["bytes"], deadline, out)
            if any(observed[key] != item[key] for key in ("bytes", "sha256")):
                raise ValueError("Source changed during COPY")
            out.flush()
            os.fsync(out.fileno())
        copied = _read_source(path, item["bytes"], deadline)
        if copied != observed:
            raise ValueError("COPY byte verification failed")
    if {p.name for p in destination.iterdir()} != {item["name"] for item in items}:
        raise ValueError("COPY file set changed")
    if _raw_inventory(source, deadline) != {item["name"]: _read_source(destination / item["name"], item["bytes"], deadline) for item in items}:
        raise ValueError("Source changed after COPY")
    for item in items:
        (destination / item["name"]).chmod(0o400)
    destination.chmod(0o500)
    manifest = {"manifest_version": "completed-raw-copy-v1", "completed": True,
                "session_id": checked["session_id"], "expected_counts": checked["expected_counts"],
                "expected_feature_sha256": checked["expected_feature_sha256"],
                "files": items, "copy_completion_provenance": "copy_bytes_directly_verified",
                "source_session_completion_provenance": checked["source_session_completion_provenance"],
                "operator_counts_provenance": checked["operator_counts_provenance"],
                "independent_completion_verified": False, "soak_acceptance": False}
    _deadline(deadline)
    _publish(manifest_path, manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    first = sub.add_parser("verify")
    for arg in ("recovery", "original", "raw-dir", "output"):
        first.add_argument("--" + arg, required=True)
    first.add_argument("--expected-approval-sha256", required=True)
    second = sub.add_parser("copy")
    for arg in ("verified", "raw-dir", "copy-dir", "manifest-out"):
        second.add_argument("--" + arg, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.command == "verify":
            verify_evidence(args.recovery, args.original, args.raw_dir, args.output,
                            expected_approval_sha256=args.expected_approval_sha256)
        else:
            copy_verified(args.verified, args.raw_dir, args.copy_dir, args.manifest_out)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Research COPY gate failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
