"""Bounded, deterministic offline prediction diagnostics; never makes paper decisions."""
from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time

from signal_desk.features.causal import (CausalFeaturePipeline, FEATURE_VERSION,
    ORDERING_VERSION, canonical_bytes, feature_digest, utc_time)
from signal_desk.replay.session import SessionInput, LegacyOrderingError, ReplayError, inventory

RUNNER_VERSION = "research-baselines-s1-v1"
PINNED_PROPOSED_SPEC_SHA256 = "681d10b800f238fe8779f6153ff17fca099bd5b30480f3f03e2d42401a528d12"
CANDIDATES = ("no_change_v1", "momentum_60s_v1", "microprice_v1", "s1_flow_30s_v1")
MAX_INPUT_BYTES = 256 * 1024 * 1024
MAX_RECORDS = 200_000
MAX_OUTPUT_ROWS = 100_000
MAX_WINDOW_EVENTS = 20_000
MAX_SPEC_BYTES = 64 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024


class ResearchError(ValueError):
    """Manifest, quality, resource or output contract failed."""


def decimal_score(value):
    return format(value.quantize(Decimal("0.00000001")), "f")


def iso(value):
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def validate_spec(spec):
    if (not isinstance(spec, dict) or
        hashlib.sha256(canonical_bytes(spec)).hexdigest() != PINNED_PROPOSED_SPEC_SHA256 or
        spec.get("experiment_version") != "s1-btcusdt-spot-v1"
        or spec.get("review_status") != "proposed_not_executed" or
        spec.get("venue") != "Binance spot" or spec.get("symbol") != "BTCUSDT" or
        spec.get("horizons_seconds") != [60, 300] or spec.get("prediction_cadence_seconds") != 30 or
        spec.get("warmup_seconds") != 60 or spec.get("rolling_trade_window_seconds") != 30 or
        spec.get("minimum_rolling_trades") != 2 or spec.get("momentum_lookback_seconds") != 60 or
        spec.get("candidates") != list(CANDIDATES) or
        spec.get("quality", {}).get("ordering_version") != ORDERING_VERSION or
        spec.get("quality", {}).get("feature_version") != FEATURE_VERSION):
        raise ResearchError("Unreviewed experiment specification")
    limits = spec.get("limits", {})
    if any(type(limits.get(key)) is not int or limits[key] <= 0 or limits[key] > cap
           for key, cap in (("max_files", 64), ("max_input_bytes", MAX_INPUT_BYTES),
                            ("max_records", MAX_RECORDS), ("max_output_rows", MAX_OUTPUT_ROWS),
                            ("max_window_events", MAX_WINDOW_EVENTS), ("max_runtime_seconds", 600))):
        raise ResearchError("Invalid bounded research limits")
    quality = spec["quality"]
    if any(quality.get(key) != value for key, value in (("depth_max_age_ms", 2000),
            ("trade_max_age_ms", 3000), ("max_spread_bps", 20),
            ("require_bridged_book", True), ("reject_gaps_and_reconnects", True))):
        raise ResearchError("Unreviewed quality policy")
    if spec.get("trial_budget", {}).get("parameter_searches") != 0:
        raise ResearchError("Parameter search requires separate review")
    return limits


def verify_inputs(raw_dir, manifest, spec, deadline):
    limits = validate_spec(spec)
    if time.monotonic() > deadline:
        raise ResearchError("Research runtime budget exhausted")
    if (not isinstance(manifest, dict) or manifest.get("manifest_version") != "research-input-v1"
        or not isinstance(manifest.get("session_id"), str) or
        not re.fullmatch(r"[0-9a-f]{32}", manifest["session_id"]) or
        not isinstance(manifest.get("spec_sha256"), str) or
        not re.fullmatch(r"[0-9a-f]{64}", manifest["spec_sha256"])):
        raise ResearchError("Invalid versioned input manifest")
    files = manifest.get("files")
    if not isinstance(files, list) or not 1 <= len(files) <= limits["max_files"]:
        raise ResearchError("Input file count outside limit")
    directory = Path(raw_dir)
    if not directory.is_dir() or directory.is_symlink():
        raise ResearchError("Raw input directory must exist without symlink")
    observed = inventory(directory)
    expected = {}
    total = 0
    for item in files:
        if not isinstance(item, dict) or set(item) != {"name", "bytes", "sha256"}:
            raise ResearchError("Invalid input file entry")
        name, size, digest = item["name"], item["bytes"], item["sha256"]
        if (not isinstance(name, str) or name not in observed or name in expected or
            type(size) is not int or size < 0 or not isinstance(digest, str) or
            not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise ResearchError("Invalid or repeated input file identity")
        total += size
        if total > limits["max_input_bytes"]:
            raise ResearchError("Input byte limit exhausted")
        path = directory / name
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size != size:
                raise ResearchError("Input size changed")
            checksum = hashlib.sha256()
            remaining = size
            while remaining:
                if time.monotonic() > deadline:
                    raise ResearchError("Research runtime budget exhausted")
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ResearchError("Input size changed")
                checksum.update(chunk)
                remaining -= len(chunk)
            if checksum.hexdigest() != digest or info.st_size != os.fstat(stream.fileno()).st_size:
                raise ResearchError("Input hash changed")
        expected[name] = size
    if set(observed) != set(expected):
        raise ResearchError("Manifest does not cover every raw JSONL file")
    counts = manifest.get("expected_counts")
    if (not isinstance(counts, dict) or set(counts) != {"book_snapshot", "book_delta", "trade"}
        or any(type(value) is not int or value < 0 for value in counts.values()) or
        counts["book_snapshot"] != 1 or sum(counts.values()) > limits["max_records"]):
        raise ResearchError("Missing or invalid independently recorded session counts")
    return observed


def run_research(raw_dir, manifest, spec, *, started=None):
    """Replay one ordered session, output one common-grid row per model/horizon.

    A final label uses only the last quote applied at or before due_at. Pending
    and invalid labels remain explicit; invalid/no-output predictions retain rows.
    """
    started = time.monotonic() if started is None else started
    limits = spec["limits"]
    deadline = started + limits["max_runtime_seconds"]
    before = verify_inputs(raw_dir, manifest, spec, deadline)
    source = SessionInput(Path(raw_dir), manifest["session_id"], deadline, 4 * 1024 * 1024)
    pipeline = None
    rows = []
    waiting = []
    history = deque()
    flow = deque()
    last_snapshot = None
    last_depth = last_trade = None
    first_at = last_at = tick = None
    counts = {"book_snapshot": 0, "book_delta": 0, "trade": 0}
    sequence = 0
    manifest_digest = hashlib.sha256(canonical_bytes(manifest)).hexdigest()

    def recent(moment, previous, age_ms):
        return previous is not None and timedelta(0) <= moment - previous <= timedelta(milliseconds=age_ms)

    def acceptable_quote(moment, quote, bridged, depth_at, trade_at):
        if quote is None or not bridged or not recent(moment, depth_at, 2000) or not recent(moment, trade_at, 3000):
            return False
        bid, ask, _, _ = quote
        return (ask - bid) * 10000 / ((ask + bid) / 2) <= 20

    def quote_value(snapshot):
        features = snapshot["features"]
        values = (features.get("best_bid"), features.get("best_ask"),
                  features.get("best_bid_qty"), features.get("best_ask_qty"))
        if any(v is None for v in values):
            return None
        bid, ask, bid_qty, ask_qty = (Decimal(str(v)) for v in values)
        if bid <= 0 or ask <= bid or bid_qty <= 0 or ask_qty <= 0:
            return None
        return bid, ask, bid_qty, ask_qty

    def finish(pending):
        label_quote = pending["quote"]
        due = pending["due"]
        if (pending["initial_mid"] is None or label_quote is None or
            not acceptable_quote(due, label_quote, pending["bridged"],
                                 pending["depth_at"], pending["trade_at"])):
            status, direction = "invalid", None
        else:
            bid, ask, _, _ = label_quote
            midpoint = (bid + ask) / 2
            delta = midpoint - pending["initial_mid"]
            status, direction = "valid", (1 if delta > 0 else -1 if delta < 0 else 0)
        for row in pending["rows"]:
            row["label_status"] = status
            row["label_direction"] = direction

    def expire_obsolete(at):
        # Strict inequalities retain events exactly on either window boundary.
        while flow and flow[0][0] < at - timedelta(seconds=30):
            flow.popleft()
        while history and history[0][0] < at - timedelta(seconds=65):
            history.popleft()

    def check_window_caps():
        for name, buffer in (("history", history), ("flow", flow)):
            if len(buffer) > limits["max_window_events"]:
                raise ResearchError(
                    f"Rolling research {name} event cap reached: "
                    f"size={len(buffer)}, cap={limits['max_window_events']}, "
                    f"first_at={buffer[0][0].isoformat().replace('+00:00', 'Z')}, "
                    f"last_at={buffer[-1][0].isoformat().replace('+00:00', 'Z')}")

    def predict(at):
        if pipeline is None:
            raise ResearchError("No synchronized ordered session")
        if time.monotonic() > deadline:
            raise ResearchError("Research runtime budget exhausted")
        expire_obsolete(at)
        check_window_caps()
        quote = quote_value(last_snapshot) if last_snapshot is not None else None
        quality = ("warmup" if at < first_at + timedelta(seconds=60) else
                   "book_or_bridge" if quote is None or not pipeline.bridged else
                   "stale" if not recent(at, last_depth, 2000) or not recent(at, last_trade, 3000) else
                   "spread" if (quote[1] - quote[0]) * 10000 / ((quote[1] + quote[0]) / 2) > 20 else "ok")
        midpoint = (quote[0] + quote[1]) / 2 if quality == "ok" else None
        old = next((item for item in reversed(history)
                    if item[0] <= at - timedelta(seconds=60)), None)
        if old is not None and (not recent(at - timedelta(seconds=60), old[0], 2000) or
                                not acceptable_quote(at - timedelta(seconds=60),
                                    old[2], old[3], old[4], old[5])):
            old = None
        buy = sum((amount for moment, amount in flow if amount > 0), Decimal(0))
        sell = -sum((amount for moment, amount in flow if amount < 0), Decimal(0))
        flow_ratio = (buy - sell) / (buy + sell) if buy + sell else None
        scores = {name: None for name in CANDIDATES}
        if quality == "ok":
            bid, ask, bid_qty, ask_qty = quote
            micro = (ask * bid_qty + bid * ask_qty) / (bid_qty + ask_qty)
            micro_div = (micro - midpoint) / (ask - bid)
            scores["no_change_v1"] = Decimal(0)
            scores["microprice_v1"] = micro_div
            if old is not None:
                scores["momentum_60s_v1"] = (midpoint - old[1]) / old[1]
            if len(flow) >= 2 and flow_ratio is not None:
                scores["s1_flow_30s_v1"] = Decimal("0.7") * flow_ratio + Decimal("0.3") * micro_div
        for horizon in (60, 300):
            group = []
            for name in CANDIDATES:
                score = scores[name]
                row = {"experiment_version": spec["experiment_version"],
                       "runner_version": RUNNER_VERSION, "input_manifest_sha256": manifest_digest,
                       "session_id": manifest["session_id"], "candidate": name,
                       "prediction_at": iso(at), "due_at": iso(at + timedelta(seconds=horizon)),
                       "horizon_seconds": horizon, "prediction_status": (
                           "invalid" if quality != "ok" else "valid" if score is not None else "no_output"),
                       "quality_reason": quality if quality != "ok" else None if score is not None else "insufficient_history_or_flow",
                       "raw_score": decimal_score(score) if score is not None else None,
                       "label_status": "pending", "label_direction": None}
                group.append(row)
                rows.append(row)
                if len(rows) > limits["max_output_rows"]:
                    raise ResearchError("Research row budget exhausted")
            waiting.append({"due": at + timedelta(seconds=horizon), "initial_mid": midpoint,
                            "quote": quote, "depth_at": last_depth, "trade_at": last_trade,
                            "bridged": pipeline.bridged,
                            "rows": group})

    for event in source.merged():
        quality = event.get("data_quality")
        if not isinstance(quality, dict) or quality.get("ordering_version") != ORDERING_VERSION:
            raise LegacyOrderingError("Legacy input lacks supported application ordering")
        if quality.get("feature_version") != FEATURE_VERSION:
            raise ResearchError("Unsupported captured feature version")
        if quality.get("gap_count", 0) != 0 or quality.get("reconnect_count", 0) != 0:
            raise ResearchError("Gapped or reconnected session unsupported for this experiment")
        if pipeline is None:
            if not isinstance(quality.get("feature_policy"), dict):
                raise ResearchError("Captured feature policy missing")
            pipeline = CausalFeaturePipeline(manifest["session_id"], quality["feature_policy"])
        at = utc_time(quality.get("applied_ts"))
        if first_at is None:
            first_at = at
            cadence = spec["prediction_cadence_seconds"]
            epoch = int(at.timestamp())
            tick = datetime.fromtimestamp((epoch // cadence + 1) * cadence, timezone.utc)
        while tick < at:
            predict(tick)
            tick += timedelta(seconds=30)
        # A transition may fall between ticks; expire before checking its new
        # state, without dropping anything needed by earlier predictions.
        expire_obsolete(at)
        for item in tuple(waiting):
            if item["due"] < at:
                finish(item)
                waiting.remove(item)
        snapshot = pipeline.apply(event)
        if feature_digest(snapshot) != quality.get("feature_sha256"):
            raise ResearchError("Capture feature hash mismatch")
        sequence += 1
        if sequence > limits["max_records"]:
            raise ResearchError("Research record budget exhausted")
        counts[event["event_type"]] += 1
        last_snapshot = snapshot
        last_at = at
        if event["event_type"] in ("book_snapshot", "book_delta"):
            last_depth = at
        elif event["event_type"] == "trade":
            last_trade = at
            qty = Decimal(event["trade_qty"])
            flow.append((at, qty if event["trade_side"] == "buy" else -qty))
        quote = quote_value(snapshot)
        # Retain every applied state, including invalid or missing books: never
        # replace the latest lookback state with an earlier acceptable quote.
        midpoint = (quote[0] + quote[1]) / 2 if quote is not None else None
        history.append((at, midpoint, quote, pipeline.bridged, last_depth, last_trade))
        for item in waiting:
            if at <= item["due"]:
                item.update(quote=quote, depth_at=last_depth, trade_at=last_trade,
                            bridged=pipeline.bridged)
        check_window_caps()
    if tick is not None and tick <= last_at:
        predict(tick)
    for item in waiting:
        if last_at >= item["due"]:
            finish(item)
    if counts != manifest["expected_counts"] or inventory(Path(raw_dir)) != before:
        raise ResearchError("Expected counts or raw input identities changed")
    return rows


def main():
    started = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    staged = None
    try:
        parent = args.output.parent.resolve(strict=True)
        raw = args.raw_dir.resolve(strict=True)
        if args.output.exists() or args.output.is_symlink() or parent == raw or parent.is_relative_to(raw):
            raise ResearchError("Output exists or overlaps raw input")
        def bounded_json(path, maximum):
            with path.open("rb") as stream:
                content = stream.read(maximum + 1)
            if len(content) > maximum:
                raise ResearchError("Metadata byte limit exhausted")
            if time.monotonic() > started + 600:
                raise ResearchError("Research runtime budget exhausted")
            return content, json.loads(content)

        spec_bytes, spec = bounded_json(args.spec, MAX_SPEC_BYTES)
        _, manifest = bounded_json(args.input_manifest, MAX_MANIFEST_BYTES)
        if manifest.get("spec_sha256") != hashlib.sha256(spec_bytes).hexdigest():
            raise ResearchError("Input manifest does not pin exact experiment specification")
        results = run_research(args.raw_dir, manifest, spec, started=started)
        fd, staged = tempfile.mkstemp(prefix=".research-", suffix=".tmp", dir=parent)
        with os.fdopen(fd, "wb") as destination:
            for result in results:
                if time.monotonic() > started + spec["limits"]["max_runtime_seconds"]:
                    raise ResearchError("Research runtime budget exhausted")
                destination.write(canonical_bytes(result) + b"\n")
            destination.flush()
            os.fsync(destination.fileno())
        if time.monotonic() > started + spec["limits"]["max_runtime_seconds"]:
            raise ResearchError("Research runtime budget exhausted")
        os.link(staged, args.output)
        return 0
    except (OSError, ValueError, KeyError, ReplayError, TypeError) as exc:
        print(f"Research failed without a valid result: {exc}", file=sys.stderr)
        return 2
    finally:
        if staged is not None:
            Path(staged).unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
