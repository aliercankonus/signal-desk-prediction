"""Offline, read-only verification and exact-byte ordered research prefix extraction."""
from __future__ import annotations

import argparse
from contextlib import ExitStack, closing
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import time

from signal_desk.features.causal import (CausalFeaturePipeline, FEATURE_VERSION,
    canonical_bytes, feature_digest, utc_time)
from signal_desk.replay.session import (SessionInput, ReplayError, identity, inventory,
    reject_constant, unique_object)
from signal_desk.research.baselines import (MAX_SPEC_BYTES, MAX_MANIFEST_BYTES,
    validate_spec)

SOURCE_SESSION_ID = "cb8a0767d7284b8aaa3d09fbca7095f2"
SOURCE_COUNTS = {"book_snapshot": 1, "book_delta": 35936, "trade": 222238}
SOURCE_FEATURE_SHA256 = "bafabf00f920c948a7f952425d105197039af0104c0b28b65904afdbe94bf6c0"
MAX_SOURCE_FILES = 64
MAX_SOURCE_BYTES = 512 * 1024 * 1024
MAX_SOURCE_RECORDS = 350_000
MAX_PREFIX_RECORDS = 90_000
MAX_PREFIX_BYTES = 128 * 1024 * 1024
MAX_RECORD_BYTES = 4 * 1024 * 1024
MAX_RUNTIME_SECONDS = 900


class ExtractError(ValueError):
    """Source, resource or publication contract failed."""


def _metadata(path, cap):
    with Path(path).open("rb") as stream:
        data = stream.read(cap + 1)
    if len(data) > cap:
        raise ExtractError("Metadata byte budget exhausted")
    return data, json.loads(data, parse_constant=reject_constant, object_pairs_hook=unique_object)


def _raw_stream(directory, names, session_id, before, deadline):
    """One-record-at-a-time exact bytes aligned with SessionInput's selected stream."""
    for name in names:
        fd = os.open(directory / name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as source:
            if not stat.S_ISREG(os.fstat(fd).st_mode) or identity(os.fstat(fd)) != before[name]:
                raise ExtractError("Source file changed before exact-byte read")
            while True:
                if time.monotonic() > deadline:
                    raise ExtractError("Extraction runtime budget exhausted")
                raw = source.readline(MAX_RECORD_BYTES + 1)
                if not raw:
                    break
                if len(raw) > MAX_RECORD_BYTES or not raw.endswith(b"\n"):
                    raise ExtractError("Invalid exact-byte record")
                event = json.loads(raw, parse_constant=reject_constant, object_pairs_hook=unique_object)
                if event["data_quality"].get("collector_session_id") == session_id:
                    yield name, event, raw
            if identity(os.fstat(fd)) != before[name]:
                raise ExtractError("Source file changed during exact-byte read")


def extract_prefix(raw_dir, source_manifest, spec_path, output_dir, *,
                   synthetic_session_id=None, max_records=MAX_PREFIX_RECORDS,
                   max_output_bytes=MAX_PREFIX_BYTES, max_runtime_seconds=MAX_RUNTIME_SECONDS):
    """Verify *all* completed source records; copy a contiguous exact-byte prefix.

    A synthetic session override is only an explicit Python test-fixture facility;
    the CLI accepts no source-session override. No manifest is published on failure.
    """
    started = time.monotonic()
    if (type(max_records) is not int or not 1 <= max_records <= MAX_PREFIX_RECORDS or
        type(max_output_bytes) is not int or not 1 <= max_output_bytes <= MAX_PREFIX_BYTES or
        not isinstance(max_runtime_seconds, (int, float)) or
        not math.isfinite(max_runtime_seconds) or not 0 < max_runtime_seconds <= MAX_RUNTIME_SECONDS):
        raise ExtractError("Invalid extraction resource budget")
    deadline = started + max_runtime_seconds
    spec_bytes, spec = _metadata(spec_path, MAX_SPEC_BYTES)
    validate_spec(spec)
    if (not isinstance(source_manifest, dict) or
        source_manifest.get("manifest_version") != "completed-raw-copy-v1" or
        source_manifest.get("completed") is not True):
        raise ExtractError("Completed raw COPY manifest required")
    sid = synthetic_session_id if synthetic_session_id is not None else SOURCE_SESSION_ID
    if (not isinstance(sid, str) or not re.fullmatch(r"[0-9a-f]{32}", sid) or
        source_manifest.get("session_id") != sid):
        raise ExtractError("Source session identity does not match pinned session")
    counts_expected = source_manifest.get("expected_counts")
    if (not isinstance(counts_expected, dict) or set(counts_expected) != set(SOURCE_COUNTS) or
        any(type(v) is not int or v < 0 for v in counts_expected.values()) or
        counts_expected["book_snapshot"] != 1 or
        (synthetic_session_id is None and counts_expected != SOURCE_COUNTS) or
        sum(counts_expected.values()) > MAX_SOURCE_RECORDS):
        raise ExtractError("Invalid independently recorded completed source counts")
    expected_feature_sha = source_manifest.get("expected_feature_sha256")
    if (synthetic_session_id is None and expected_feature_sha != SOURCE_FEATURE_SHA256) or (
        expected_feature_sha is not None and
        (not isinstance(expected_feature_sha, str) or
         not re.fullmatch(r"[0-9a-f]{64}", expected_feature_sha))):
        raise ExtractError("Invalid independently recorded ordered feature digest")
    directory = Path(raw_dir)
    if directory.is_symlink() or not directory.is_dir():
        raise ExtractError("Raw COPY directory must be a real directory")
    directory = directory.resolve(strict=True)
    writable_bits = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
    if directory.stat().st_mode & writable_bits:
        raise ExtractError("Raw COPY directory must be read-only")
    parent = Path(output_dir).absolute().parent.resolve(strict=True)
    if parent == directory or parent.is_relative_to(directory) or directory.is_relative_to(parent / Path(output_dir).name):
        raise ExtractError("Output must be outside source raw directory")
    output = parent / Path(output_dir).name
    if output.exists() or output.is_symlink():
        raise FileExistsError("Output directory already exists")
    before = inventory(directory)
    if any((directory / name).stat(follow_symlinks=False).st_mode & writable_bits
           for name in before):
        raise ExtractError("Raw COPY files must be read-only")
    files = source_manifest.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_SOURCE_FILES or len(files) != len(before):
        raise ExtractError("Source manifest must cover every raw file")
    expected_files = {}
    total_bytes = 0
    for item in files:
        if not isinstance(item, dict) or set(item) != {"name", "bytes", "sha256"}:
            raise ExtractError("Invalid source file identity")
        name, size, digest = item["name"], item["bytes"], item["sha256"]
        if (not isinstance(name, str) or name not in before or name in expected_files or
            type(size) is not int or size < 0 or size != before[name][2] or
            not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise ExtractError("Source file identity does not match COPY manifest")
        expected_files[name] = (size, digest)
        total_bytes += size
        if total_bytes > MAX_SOURCE_BYTES:
            raise ExtractError("Source byte budget exhausted")
    source = SessionInput(directory, sid, deadline, MAX_RECORD_BYTES)
    if source.before != before:
        raise ExtractError("Raw COPY inventory changed")
    # Keep the directory as an explicitly incomplete artifact until both manifests
    # are available; never remove a failed directory or overwrite prior results.
    output.mkdir(mode=0o700)
    prefix_counts = {kind: 0 for kind in SOURCE_COUNTS}
    full_counts = {kind: 0 for kind in SOURCE_COUNTS}
    full_feature_digest = hashlib.sha256()
    output_files = {}
    pipeline = None
    first_at = last_at = None
    used = selected = 0
    prefix_bridged = False
    truncation = None
    streams = {}
    try:
        with ExitStack() as stack:
            for kind in ("depth", "trade"):
                names = sorted(n for n in before if f"_{kind}_" in n)
                streams[kind] = stack.enter_context(
                    closing(_raw_stream(directory, names, sid, before, deadline)))
            destinations = {}
            for event in source.merged():
                if time.monotonic() > deadline:
                    raise ExtractError("Extraction runtime budget exhausted")
                quality = event["data_quality"]
                if quality.get("feature_version") != FEATURE_VERSION:
                    raise ExtractError("Unsupported source feature version")
                if quality.get("gap_count", 0) != 0 or quality.get("reconnect_count", 0) != 0:
                    raise ExtractError("Gapped or reconnected source unsupported")
                if pipeline is None:
                    if not isinstance(quality.get("feature_policy"), dict):
                        raise ExtractError("Source feature policy missing")
                    pipeline = CausalFeaturePipeline(sid, quality["feature_policy"])
                snapshot = pipeline.apply(event)
                if feature_digest(snapshot) != quality.get("feature_sha256"):
                    raise ExtractError("Source capture feature hash mismatch")
                full_feature_digest.update(canonical_bytes(snapshot) + b"\n")
                full_counts[event["event_type"]] += 1
                if sum(full_counts.values()) > MAX_SOURCE_RECORDS:
                    raise ExtractError("Source record budget exhausted")
                if truncation is not None:
                    continue
                kind = "trade" if event["event_type"] == "trade" else "depth"
                name, original, raw = next(streams[kind])
                if original != event:
                    raise ExtractError("Exact-byte reader diverged from ordered source")
                seq = quality["ingest_sequence"]
                if seq != selected + 1:
                    raise ExtractError("Prefix must start at sequence 1 without gaps")
                if selected >= max_records:
                    truncation = "record_limit"
                    continue
                if used + len(raw) > max_output_bytes:
                    truncation = "byte_limit"
                    continue
                if name not in destinations:
                    destinations[name] = stack.enter_context((output / name).open("xb"))
                    output_files[name] = {"name": name, "bytes": 0, "sha256": hashlib.sha256()}
                destinations[name].write(raw)
                output_files[name]["bytes"] += len(raw)
                output_files[name]["sha256"].update(raw)
                used += len(raw)
                selected += 1
                prefix_bridged = pipeline.bridged
                prefix_counts[event["event_type"]] += 1
                at = utc_time(quality["applied_ts"])
                first_at = at if first_at is None else first_at
                last_at = at
            if pipeline is None or not pipeline.bridged or full_counts != counts_expected:
                raise ExtractError("Completed source counts or snapshot bridge mismatch")
            if expected_feature_sha is not None and full_feature_digest.hexdigest() != expected_feature_sha:
                raise ExtractError("Completed source ordered feature digest mismatch")
            if selected == 0 or prefix_counts["book_snapshot"] != 1 or not output_files or not prefix_bridged:
                raise ExtractError("Prefix lacks a starting snapshot and depth bridge")
            for name, destination in destinations.items():
                destination.flush()
                os.fsync(destination.fileno())
        if time.monotonic() > deadline or inventory(directory) != before or any(
            (directory / name).stat(follow_symlinks=False).st_mode & writable_bits
            for name in before):
            raise ExtractError("Source inventory or runtime changed")
        if set(source.files) != set(expected_files) or any(
            source.files[name]["bytes"] != size or source.files[name]["sha256"] != digest
            for name, (size, digest) in expected_files.items()):
            raise ExtractError("Source COPY file SHA-256 mismatch")
        prefix_files = [{"name": name, "bytes": item["bytes"],
                         "sha256": item["sha256"].hexdigest()}
                        for name, item in sorted(output_files.items())]
        duration = (last_at - first_at).total_seconds()
        result = {"manifest_version": "research-extraction-v1", "status": "complete_prefix",
                  "source_session_id": sid, "source_manifest_sha256": hashlib.sha256(
                      canonical_bytes(source_manifest)).hexdigest(),
                  "source_files": sorted(files, key=lambda item: item["name"]),
                  "source_expected_counts": counts_expected, "source_verified_counts": full_counts,
                  "source_capture_hashes_verified": sum(full_counts.values()),
                  "source_verified_feature_sha256": full_feature_digest.hexdigest(),
                  "selection_policy": {"start_ingest_sequence": 1, "max_records": max_records,
                                       "max_serialized_raw_bytes": max_output_bytes,
                                       "stop_before_exceeding_either_limit": True},
                  "selected_records": selected, "selected_counts": prefix_counts,
                  "first_ingest_sequence": 1, "last_ingest_sequence": selected,
                  "first_applied_ts": first_at.isoformat(), "last_applied_ts": last_at.isoformat(),
                  "usable_duration_seconds": duration,
                  "usable_duration_status": ("insufficient_for_proposed_60_day_split"
                      if duration < 60 * 86400 else "duration_only_not_split_approved"),
                  "serialized_raw_bytes": used, "output_files": prefix_files,
                  "truncation_scope": truncation or "source_end",
                  "scope": "verified stored source and raw prefix; not full-session research, exchange completeness, model selection or PnL"}
        input_manifest = {"manifest_version": "research-input-v1", "session_id": sid,
                          "spec_sha256": hashlib.sha256(spec_bytes).hexdigest(),
                          "expected_counts": prefix_counts, "files": prefix_files}
        for filename, payload in (("extraction-v1.json", result),
                                  ("research-input-v1.json", input_manifest)):
            # Publishing the runner manifest is the last action. A failed source
            # scan or fsync leaves an incomplete output without a usable manifest.
            if time.monotonic() > deadline:
                raise ExtractError("Extraction runtime budget exhausted")
            tmp = output / ("." + filename + ".incomplete")
            with tmp.open("xb") as destination:
                destination.write(canonical_bytes(payload) + b"\n")
                destination.flush()
                os.fsync(destination.fileno())
            if time.monotonic() > deadline:
                raise ExtractError("Extraction runtime budget exhausted")
            os.link(tmp, output / filename)
        return result
    except Exception:
        # Retain the incomplete directory; the runner manifest was never published.
        raise



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        _, source = _metadata(args.source_manifest, MAX_MANIFEST_BYTES)
        result = extract_prefix(args.raw_dir, source, args.spec, args.output_dir)
    except (OSError, ValueError, ReplayError, KeyError, TypeError, StopIteration) as exc:
        print(f"Extraction failed without valid research input: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
