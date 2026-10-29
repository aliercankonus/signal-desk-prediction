"""Offline, paper-only research gates with real captured feature transitions."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from signal_desk.collector.binance_mapping import map_snapshot, map_depth_delta, map_trade
from signal_desk.features.causal import CausalFeaturePipeline, feature_digest, canonical_bytes
from signal_desk.research.baselines import run_research, ResearchError
from signal_desk.research import baselines
from signal_desk.replay.session import LegacyOrderingError

SPEC = Path(__file__).resolve().parents[2] / "docs/research/s1_experiment_v1.json"
BASE = datetime(2026, 10, 28, tzinfo=timezone.utc)
SID = "c" * 32


def fixture(tmp_path, times=(0, 1, 2, 30, 30, 60, 60, 90, 90, 120, 120,
                             150, 150, 180, 180, 210, 210, 240, 240,
                             270, 270, 300, 300, 330, 330, 360, 360), policy=None,
            wide_ask_at=None, ask_updates=None, trades_only=False):
    raw = tmp_path / "raw"
    raw.mkdir()
    pipeline = CausalFeaturePipeline(SID, policy)
    depth_id = 10
    trade_id = 1
    rows = []
    for index, second in enumerate(times, 1):
        stamp = (BASE + timedelta(seconds=second)).isoformat()
        if index == 1:
            event = map_snapshot({"lastUpdateId": 10, "bids": [["100", "2"]], "asks": [["100.10", "1"]]}, received_ts=stamp)
        elif trades_only or index % 2:
            event = map_trade({"t": trade_id, "T": 1, "p": "100.05", "q": "0.25", "m": index % 4 == 1})
            trade_id += 1
        else:
            depth_id += 1
            event = map_depth_delta({"U": depth_id, "u": depth_id, "E": 1,
                                     "b": [["100", str(2 + index % 3)]],
                                     "a": (ask_updates or {}).get(second,
                                          [["100.10", "0"], ["102", "1"]]
                                          if second == wide_ask_at else [])})
            event["previous_final_update_id"] = depth_id - 1
        event["exchange_ts"] = stamp
        event["received_ts"] = stamp
        event["monotonic_ns"] = second * 1_000_000_000 + index
        event["data_quality"] = {**event.get("data_quality", {}),
            "collector_session_id": SID, "ordering_version": "session-applied-v1",
            "ingest_sequence": index, "applied_ts": stamp,
            "applied_monotonic_ns": event["monotonic_ns"] + 1,
            "feature_policy": pipeline.policy, "feature_version": "features-v17-applied-l2-trade"}
        snapshot = pipeline.apply(event)
        event["data_quality"]["feature_sha256"] = feature_digest(snapshot)
        rows.append(event)
    for suffix in ("depth", "trade"):
        selected = [r for r in rows if (r["event_type"] == "trade") == (suffix == "trade")]
        if selected:
            (raw / f"binance_btcusdt_{suffix}_2026-10-28.jsonl").write_bytes(
                b"".join(canonical_bytes(r) + b"\n" for r in selected))
    spec = json.loads(SPEC.read_text())
    manifest = {"manifest_version": "research-input-v1", "session_id": SID,
                "spec_sha256": hashlib.sha256(SPEC.read_bytes()).hexdigest(),
                "expected_counts": {kind: sum(r["event_type"] == kind for r in rows)
                                    for kind in ("book_snapshot", "book_delta", "trade")},
                "files": [{"name": p.name, "bytes": p.stat().st_size,
                           "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                          for p in sorted(raw.glob("*.jsonl"))]}
    return raw, manifest, spec, rows


def test_burst_older_than_both_windows_does_not_false_trip_event_cap(tmp_path):
    # At t=60 the previous tick cannot drop t=0 history (65-second retention).
    # At t=66, the next transition must expire it before checking the cap.
    raw, manifest, spec, _ = fixture(tmp_path, times=(0,) * 20_000 + (66,))
    rows = run_research(raw, manifest, spec)
    assert {row["prediction_at"] for row in rows} == {
        "2026-10-28T00:00:30Z", "2026-10-28T00:01:00Z"}
    assert len(rows) == 2 * len(spec["candidates"]) * len(spec["horizons_seconds"])


def test_required_rolling_flow_over_cap_names_buffer_size_and_span(tmp_path):
    raw, manifest, spec, _ = fixture(tmp_path, times=(0,) * 20_002, trades_only=True)
    with pytest.raises(ResearchError, match=(
        r"Rolling research flow event cap reached: size=20001, cap=20000, "
        r"first_at=2026-10-28T00:00:00Z, last_at=2026-10-28T00:00:00Z")):
        run_research(raw, manifest, spec)


def test_dense_history_over_old_event_cap_keeps_every_verified_transition(tmp_path):
    # 20,001 applied states at one timestamp; only ~10,000 are trades.
    # Old per-event history rejects this before the first prediction tick.
    raw, manifest, spec, _ = fixture(tmp_path,
        times=(0,) * 20_001 + (30, 30, 60, 60, 90, 90, 120, 120))
    results = run_research(raw, manifest, spec)
    assert len(results) == 4 * len(spec["horizons_seconds"]) * len(spec["candidates"])
    assert {r["prediction_at"] for r in results} == {
        "2026-10-28T00:00:30Z", "2026-10-28T00:01:00Z",
        "2026-10-28T00:01:30Z", "2026-10-28T00:02:00Z"}
    assert manifest["expected_counts"]["trade"] < 20_000


def test_grid_asof_states_match_naive_full_history_at_exact_boundaries():
    from signal_desk.research.baselines import GridAsOfHistory
    grid = GridAsOfHistory(BASE + timedelta(seconds=30))
    applied = []
    for index, second in enumerate((0, 0, 1, 29, 30, 30, 31, 59, 60, 60,
                                    61, 89, 90, 90, 91, 119, 120, 120, 121, 600)):
        at = BASE + timedelta(seconds=second)
        while grid.tick < at:
            cutoff = grid.tick - timedelta(seconds=60)
            expected = next((item for item in reversed(applied) if item[0] <= cutoff), None)
            assert grid.sample() == expected
            grid.advance()
        # The tuple contains an invalid/missing quote and freshness/bridge
        # metadata; an equal-timestamp later state must replace an earlier one.
        state = (at, index, None if index % 2 else "quote", index % 3 == 0,
                 at - timedelta(seconds=1), at - timedelta(seconds=2))
        grid.observe(state)
        applied.append(state)
        assert grid.retained_count <= 4
    cutoff = grid.tick - timedelta(seconds=60)
    assert grid.sample() == next((item for item in reversed(applied) if item[0] <= cutoff), None)


@pytest.mark.parametrize("times,ask_updates,reference_sha256", [
    ((0, 1, 2, 30, 30, 58, 58, 59, 59, 60, 60, 61, 61, 90, 90, 120, 120),
     {59: [["100.10", "0"], ["102", "1"]],
      60: [["102", "0"], ["100.10", "1"]]},
     "b32e9238a2ac954e8edd191d139ccfa420ae18245a0b5b296bfd6b88ae90cc9c"),
    ((0, 1, 2, 30, 30, 60, 60, 90, 90, 120, 120), None,
     "b6907ce7983026de9ef75f1a8205a86e261c72511713e7abc8ec95045cd70e89"),
])
def test_compact_history_preserves_full_reference_rows(tmp_path, times, ask_updates, reference_sha256):
    # Recorded from the unoptimized full-history runner on these bounded
    # synthetic captures; compare the complete ordered rows, not just momentum.
    raw, manifest, spec, _ = fixture(tmp_path, times=times, ask_updates=ask_updates)
    rows = run_research(raw, manifest, spec)
    encoded = b"".join(canonical_bytes(row) + b"\n" for row in rows)
    assert hashlib.sha256(encoded).hexdigest() == reference_sha256


def test_tampered_middle_capture_hash_still_fails_after_input_hash_update(tmp_path):
    raw, manifest, spec, _ = fixture(tmp_path)
    path = next(raw.glob("*trade*.jsonl"))
    events = [json.loads(line) for line in path.read_text().splitlines()]
    events[len(events) // 2]["data_quality"]["feature_sha256"] = "0" * 64
    path.write_bytes(b"".join(canonical_bytes(event) + b"\n" for event in events))
    for entry in manifest["files"]:
        if entry["name"] == path.name:
            entry["bytes"] = path.stat().st_size
            entry["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ResearchError, match="Capture feature hash mismatch"):
        run_research(raw, manifest, spec)


def test_common_grid_and_warmup_keep_invalid_rows(tmp_path):
    raw, manifest, spec, _ = fixture(tmp_path)
    results = run_research(raw, manifest, spec)
    grouped = {}
    for row in results:
        grouped.setdefault((row["prediction_at"], row["horizon_seconds"]), []).append(row)
    assert grouped
    assert all([r["candidate"] for r in group] == spec["candidates"] for group in grouped.values())
    first = grouped[min(grouped)]
    assert all(r["prediction_status"] == "invalid" for r in first)
    assert all(r["raw_score"] is None for r in first)


def test_future_append_does_not_change_past_scores(tmp_path):
    raw, manifest, spec, _ = fixture(tmp_path, times=(0, 1, 2, 30, 30, 60, 60, 90, 90))
    before = run_research(raw, manifest, spec)
    other = tmp_path / "other"
    other.mkdir()
    raw2, manifest2, spec2, _ = fixture(other)
    after = run_research(raw2, manifest2, spec2)
    def decision(rows):
        return [(r["candidate"], r["raw_score"], r["prediction_status"])
                for r in rows if r["prediction_at"] == "2026-10-28T00:01:00Z"]
    assert decision(before) == decision(after)


def test_s1_uses_recent_aggressor_trades_not_lifetime_totals(tmp_path):
    raw, manifest, spec, _ = fixture(tmp_path, times=(0, 1, 2, 30, 30, 60, 60))
    rows = run_research(raw, manifest, spec)
    group = {r["candidate"]: r for r in rows if r["prediction_at"] == "2026-10-28T00:01:00Z"
             and r["horizon_seconds"] == 60}
    assert group["no_change_v1"]["raw_score"] == "0.00000000"
    assert group["microprice_v1"]["raw_score"] == "0.16666667"
    # Trade at t=2s is outside the 30-second flow window; lifetime totals differ.
    assert group["s1_flow_30s_v1"]["raw_score"] == "0.05000000"
    assert group["momentum_60s_v1"]["prediction_status"] == "no_output"


def test_stale_trade_at_prediction_time_blocks_all_candidates(tmp_path):
    raw, manifest, spec, _ = fixture(tmp_path, times=(0, 1, 2, 30, 30, 60, 65))
    group = [r for r in run_research(raw, manifest, spec)
             if r["prediction_at"] == "2026-10-28T00:01:00Z"]
    assert group and all(r["prediction_status"] == "invalid" and
                         r["quality_reason"] == "stale" for r in group)


def test_due_time_wide_spread_is_not_a_valid_label(tmp_path):
    raw, manifest, spec, _ = fixture(tmp_path,
        times=(0, 1, 2, 30, 30, 60, 60, 90, 90, 120, 120), wide_ask_at=120)
    target = [r for r in run_research(raw, manifest, spec)
              if r["prediction_at"] == "2026-10-28T00:01:00Z"
              and r["horizon_seconds"] == 60]
    assert target and all(r["label_status"] == "invalid" for r in target)


def test_due_time_stale_trade_is_not_a_valid_label(tmp_path):
    raw, manifest, spec, _ = fixture(tmp_path,
        times=(0, 1, 2, 30, 30, 60, 60, 90, 90, 120))
    target = [r for r in run_research(raw, manifest, spec)
              if r["prediction_at"] == "2026-10-28T00:01:00Z"
              and r["horizon_seconds"] == 60]
    assert target and all(r["label_status"] == "invalid" for r in target)


def test_due_at_never_uses_future_quote(tmp_path):
    raw, manifest, spec, _ = fixture(tmp_path, times=(0, 1, 2, 30, 30, 60, 60, 91, 91, 121, 121))
    rows = run_research(raw, manifest, spec)
    target = [r for r in rows if r["prediction_at"] == "2026-10-28T00:00:30Z"
              and r["horizon_seconds"] == 60]
    assert target and all(r["label_status"] == "invalid" for r in target)
    assert all(r["label_direction"] is None for r in target)


def test_valid_prediction_uses_no_quote_after_its_due_at(tmp_path):
    raw, manifest, spec, _ = fixture(tmp_path, times=(0, 1, 2, 30, 30, 60, 60,
                                                      90, 90, 121, 121, 151, 151))
    rows = run_research(raw, manifest, spec)
    target = [r for r in rows if r["prediction_at"] == "2026-10-28T00:01:00Z"
              and r["horizon_seconds"] == 60]
    assert target and any(r["prediction_status"] == "valid" for r in target)
    assert all(r["due_at"] == "2026-10-28T00:02:00Z" and
               r["label_status"] == "invalid" and r["label_direction"] is None for r in target)


def test_300_second_label_uses_exact_due_quote(tmp_path):
    raw, manifest, spec, _ = fixture(tmp_path)
    rows = run_research(raw, manifest, spec)
    target = [r for r in rows if r["prediction_at"] == "2026-10-28T00:01:00Z"
              and r["horizon_seconds"] == 300]
    assert target and all(r["due_at"] == "2026-10-28T00:06:00Z" and
                          r["label_status"] == "valid" for r in target)


def test_pending_and_no_output_preserved(tmp_path):
    raw, manifest, spec, _ = fixture(tmp_path, times=(0, 1, 2, 30, 30, 60, 60, 90, 90))
    rows = run_research(raw, manifest, spec)
    assert any(r["label_status"] == "pending" for r in rows)
    assert any(r["prediction_status"] == "no_output" for r in rows)


def test_warmup_invalid_prediction_still_has_pending_future_label(tmp_path):
    raw, manifest, spec, _ = fixture(tmp_path, times=(0, 1, 2, 30, 30))
    rows = run_research(raw, manifest, spec)
    target = [r for r in rows if r["prediction_at"] == "2026-10-28T00:00:30Z"
              and r["horizon_seconds"] == 300]
    assert target and all(r["prediction_status"] == "invalid" and
                          r["label_status"] == "pending" for r in target)


def test_legacy_ordering_is_unsupported_even_with_updated_input_hash(tmp_path):
    raw, manifest, spec, _ = fixture(tmp_path)
    file = next(raw.glob("*depth*.jsonl"))
    content = [json.loads(x) for x in file.read_text().splitlines()]
    del content[0]["data_quality"]["ordering_version"]
    file.write_bytes(b"".join(canonical_bytes(r) + b"\n" for r in content))
    for item in manifest["files"]:
        if item["name"] == file.name:
            item["bytes"] = file.stat().st_size
            item["sha256"] = hashlib.sha256(file.read_bytes()).hexdigest()
    with pytest.raises(LegacyOrderingError):
        run_research(raw, manifest, spec)


def test_depth_gap_fails_closed(tmp_path):
    raw, manifest, spec, _ = fixture(tmp_path)
    file = next(raw.glob("*depth*.jsonl"))
    content = [json.loads(x) for x in file.read_text().splitlines()]
    content[1]["previous_final_update_id"] = 999
    file.write_bytes(b"".join(canonical_bytes(r) + b"\n" for r in content))
    for item in manifest["files"]:
        if item["name"] == file.name:
            item["bytes"] = file.stat().st_size
            item["sha256"] = hashlib.sha256(file.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        run_research(raw, manifest, spec)


def test_capture_policy_is_verified_without_replacing_fixed_research_gate(tmp_path):
    raw, manifest, spec, _ = fixture(tmp_path, policy={"stale_l2_ms": 1500,
        "stale_trades_ms": 2500, "max_book_levels": 20000})
    assert run_research(raw, manifest, spec)


def test_strict_capture_freshness_does_not_override_fixed_research_gate(tmp_path):
    raw, manifest, spec, _ = fixture(tmp_path, times=(0, 1, 2, 30, 30, 59, 60),
        policy={"stale_l2_ms": 500, "stale_trades_ms": 500, "max_book_levels": 20000})
    target = [r for r in run_research(raw, manifest, spec)
              if r["prediction_at"] == "2026-10-28T00:01:00Z"]
    assert target and any(r["candidate"] == "no_change_v1" and
                          r["prediction_status"] == "valid" for r in target)


def test_momentum_lookback_requires_trade_freshness_at_lookback_cutoff(tmp_path):
    raw, manifest, spec, _ = fixture(tmp_path,
        times=(0, 1, 2, 30, 30, 55, 56, 58, 120, 120, 120))
    group = {r["candidate"]: r for r in run_research(raw, manifest, spec)
             if r["prediction_at"] == "2026-10-28T00:02:00Z"
             and r["horizon_seconds"] == 60}
    assert group["no_change_v1"]["prediction_status"] == "valid"
    assert group["momentum_60s_v1"]["prediction_status"] == "no_output"


@pytest.mark.parametrize("invalid_asks", [
    [["100.10", "0"], ["102", "1"]],
    [["100.10", "0"]],
])
def test_momentum_never_falls_back_past_latest_invalid_lookback_state(tmp_path, invalid_asks):
    restore = [["102", "0"], ["100.10", "1"]] if len(invalid_asks) == 2 else [["100.10", "1"]]
    raw, manifest, spec, _ = fixture(tmp_path,
        times=(0, 1, 2, 30, 30, 58, 58, 59, 59, 120, 120),
        ask_updates={59: invalid_asks, 120: restore})
    group = [r for r in run_research(raw, manifest, spec)
             if r["prediction_at"] == "2026-10-28T00:02:00Z"]
    assert len(group) == len(spec["candidates"]) * 2
    assert {r["horizon_seconds"] for r in group} == {60, 300}
    assert all({r["candidate"] for r in group if r["horizon_seconds"] == horizon}
               == set(spec["candidates"]) for horizon in (60, 300))
    assert all(r["prediction_status"] == "valid" for r in group
               if r["candidate"] == "no_change_v1")
    assert all(r["prediction_status"] == "no_output" and r["raw_score"] is None
               for r in group if r["candidate"] == "momentum_60s_v1")
    assert {r["prediction_at"] for r in group} == {"2026-10-28T00:02:00Z"}


def test_momentum_valid_lookback_just_before_cutoff(tmp_path):
    raw, manifest, spec, _ = fixture(tmp_path, times=(0, 1, 2, 30, 30, 58, 59, 120, 120))
    target = [r for r in run_research(raw, manifest, spec)
              if r["prediction_at"] == "2026-10-28T00:02:00Z"
              and r["candidate"] == "momentum_60s_v1"]
    assert len(target) == 2 and all(r["prediction_status"] == "valid" for r in target)


def test_momentum_exact_lookback_cutoff_ignores_later_invalid_state(tmp_path):
    raw, manifest, spec, _ = fixture(tmp_path,
        times=(0, 1, 2, 30, 30, 59, 60, 61, 61, 120, 120),
        ask_updates={61: [["100.10", "0"], ["102", "1"]],
                     120: [["102", "0"], ["100.10", "1"]]})
    target = [r for r in run_research(raw, manifest, spec)
              if r["prediction_at"] == "2026-10-28T00:02:00Z"
              and r["candidate"] == "momentum_60s_v1"]
    assert len(target) == 2 and all(r["prediction_status"] == "valid" and
                                    r["raw_score"] == "0.00000000" for r in target)


def test_oversized_manifest_entry_fails_before_hashing(tmp_path):
    raw, manifest, spec, _ = fixture(tmp_path)
    path = next(raw.glob("*depth*.jsonl"))
    with path.open("ab") as stream:
        stream.truncate(268435457)
    for entry in manifest["files"]:
        if entry["name"] == path.name:
            entry["bytes"] = path.stat().st_size
            entry["sha256"] = "0" * 64
    with pytest.raises(ResearchError, match="byte limit"):
        run_research(raw, manifest, spec)


@pytest.mark.parametrize("field,replacement", [
    ("prediction_clock", "venue timestamp"),
    ("label", {"quote": "first quote after due_at"}),
    ("s1_score", "different score"),
    ("trial_budget", {"s1_precommitted_variants": 100}),
])
def test_versioned_spec_rejects_any_unreviewed_semantic_change(tmp_path, field, replacement):
    raw, manifest, spec, _ = fixture(tmp_path)
    spec[field] = {**spec[field], **replacement} if isinstance(replacement, dict) else replacement
    with pytest.raises(ResearchError, match="Unreviewed experiment specification"):
        run_research(raw, manifest, spec)


def test_input_growth_during_hash_never_reads_past_declared_size(tmp_path, monkeypatch):
    raw, manifest, spec, _ = fixture(tmp_path)
    path = next(raw.glob("*depth*.jsonl"))
    original_size = path.stat().st_size
    inode = path.stat().st_ino
    fdopen = baselines.os.fdopen
    observed = []
    appended = False

    class TrackedStream:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self.stream, name)

        def read(self, amount):
            nonlocal appended
            if not appended:
                appended = True
                with path.open("ab") as target:
                    target.write(b"x" * 1024)
            data = self.stream.read(amount)
            observed.append(len(data))
            return data

    def tracked_fdopen(fd, mode):
        stream = fdopen(fd, mode)
        return TrackedStream(stream) if baselines.os.fstat(fd).st_ino == inode else stream

    monkeypatch.setattr(baselines.os, "fdopen", tracked_fdopen)
    with pytest.raises(ResearchError):
        run_research(raw, manifest, spec)
    assert observed and sum(observed) <= original_size


def test_cli_is_deterministic_and_never_overwrites(tmp_path):
    raw, manifest, _, _ = fixture(tmp_path)
    path = tmp_path / "input.json"
    path.write_text(json.dumps(manifest))
    outputs = (tmp_path / "run-one.jsonl", tmp_path / "run-two.jsonl")
    for output in outputs:
        call = [sys.executable, "-m", "signal_desk.research.baselines", "--raw-dir", str(raw),
                "--input-manifest", str(path), "--spec", str(SPEC), "--output", str(output)]
        result = subprocess.run(call, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert subprocess.run(call, capture_output=True).returncode != 0
    assert outputs[0].read_bytes() == outputs[1].read_bytes()
    assert all("pnl" not in r and "probability" not in r
               for r in (json.loads(line) for line in outputs[0].read_text().splitlines()))


def test_output_under_raw_directory_is_rejected(tmp_path):
    raw, manifest, _, _ = fixture(tmp_path)
    nested = raw / "outputs"
    nested.mkdir()
    path = tmp_path / "input.json"
    path.write_text(json.dumps(manifest))
    output = nested / "research.jsonl"
    result = subprocess.run([sys.executable, "-m", "signal_desk.research.baselines",
        "--raw-dir", str(raw), "--input-manifest", str(path), "--spec", str(SPEC),
        "--output", str(output)], capture_output=True, text=True)
    assert result.returncode != 0 and not output.exists()


def test_failed_output_fsync_does_not_publish_partial_artifact(tmp_path, monkeypatch):
    raw, manifest, _, _ = fixture(tmp_path)
    path = tmp_path / "input.json"
    path.write_text(json.dumps(manifest))
    output = tmp_path / "failed.jsonl"
    monkeypatch.setattr(sys, "argv", ["research", "--raw-dir", str(raw),
        "--input-manifest", str(path), "--spec", str(SPEC), "--output", str(output)])
    def fail_fsync(_):
        raise OSError("simulated disk failure")
    monkeypatch.setattr(baselines.os, "fsync", fail_fsync)
    assert baselines.main() != 0
    assert not output.exists()


@pytest.mark.parametrize("oversize", ["spec", "manifest"])
def test_cli_rejects_oversized_metadata_without_output(tmp_path, oversize):
    raw, manifest, _, _ = fixture(tmp_path)
    spec_path = tmp_path / "spec.json"
    spec_path.write_bytes(SPEC.read_bytes() + (b" " * (65537 if oversize == "spec" else 0)))
    manifest["spec_sha256"] = hashlib.sha256(spec_path.read_bytes()).hexdigest()
    path = tmp_path / "manifest.json"
    path.write_bytes(json.dumps(manifest).encode() + (b" " * (1048577 if oversize == "manifest" else 0)))
    output = tmp_path / "result.jsonl"
    result = subprocess.run([sys.executable, "-m", "signal_desk.research.baselines",
        "--raw-dir", str(raw), "--input-manifest", str(path), "--spec", str(spec_path),
        "--output", str(output)], capture_output=True, text=True)
    assert result.returncode != 0 and not output.exists()
