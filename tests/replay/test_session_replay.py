"""Captured application order, parity, failure atomicity and bounded resources."""
from copy import deepcopy
import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tracemalloc

import pytest

from signal_desk.collector import binance_collector as collector
from signal_desk.collector.binance_mapping import map_snapshot, map_depth_delta, map_trade
from signal_desk.collector.order_book_state import OrderBookGap
from signal_desk.features.causal import CausalFeaturePipeline, feature_digest, canonical_bytes
from signal_desk.replay.session import replay_session, ReplayError, LegacyOrderingError
from signal_desk.schemas.validate import SchemaValidationError


@pytest.fixture
def capture(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    raw.mkdir()
    config = {"storage": {"raw_path": str(raw)}, "exchange": {"symbol": "BTCUSDT"}}
    applied = {"index": 0, "ns": 1_000_000, "at": "2026-10-28T00:00:00Z"}
    base = datetime(2026, 10, 28, tzinfo=timezone.utc)
    online = []
    digest = collector.feature_digest
    def remember(snapshot):
        online.append(deepcopy(snapshot))
        return digest(snapshot)
    monkeypatch.setattr(collector, "feature_digest", remember)
    monkeypatch.setattr(collector, "utc_now_iso", lambda: applied["at"])
    monkeypatch.setattr(collector.time, "monotonic_ns", lambda: applied["ns"])
    # Keep real capture logic; avoid fsync cost for fixture generation only.
    def append(path, event):
        with Path(path).open("ab") as stream:
            stream.write(canonical_bytes(event) + b"\n")
    monkeypatch.setattr(collector, "append_jsonl", append)
    def emit(event, *, receipt_ns=None, advance_ns=1000):
        applied["index"] += 1
        applied["ns"] += advance_ns
        applied["at"] = (base + timedelta(microseconds=applied["index"])).isoformat()
        event["monotonic_ns"] = receipt_ns if receipt_ns is not None else applied["ns"] - 100
        event["received_ts"] = base.isoformat()
        collector.write_event(config, event)
    emit(map_snapshot({"lastUpdateId": 10, "bids": [["100", "2"]], "asks": [["102", "1"]]},
                      received_ts="2026-10-28T00:00:00Z"))
    session = config["_capture_features"].session_id
    def trade(number, **kwargs):
        emit(map_trade({"t": number, "T": 1, "p": "101", "q": "0.25", "m": False}), **kwargs)
    def depth(number=11, **kwargs):
        event = map_depth_delta({"U": number, "u": number, "E": 1,
                                 "b": [["100", "3"]], "a": []})
        event["previous_final_update_id"] = number - 1
        emit(event, **kwargs)
    return raw, session, emit, trade, depth, online, config


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def rewrite(path, events):
    path.write_bytes(b"".join(canonical_bytes(event) + b"\n" for event in events))


def depth_file(raw):
    return next(raw.glob("*depth*.jsonl"))


def trade_file(raw):
    return next(raw.glob("*trade*.jsonl"))


def test_replay_matches_real_capture_and_application_clock(capture, tmp_path):
    raw, session, emit, trade, depth, online, config = capture
    # WS trade arrived before REST, but snapshot was applied first. Venue time
    # is deliberately 1970; receipt sorting would put the trade before snapshot.
    trade(1, receipt_ns=100)
    depth()
    trade(2)
    output = tmp_path / "features.jsonl"
    expected = {"book_snapshot": 1, "book_delta": 1, "trade": 2}
    result = replay_session(raw, session, output_path=output, expected=expected)
    assert result["records"] == result["capture_hashes_verified"] == 4
    assert rows(output) == online
    assert result["counts"] == expected
    assert result["feature_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert online[0]["data_quality"]["ready"] is False
    assert online[1]["data_quality"]["ready"] is False
    assert online[2]["data_quality"]["ready"] is True
    assert online[-1]["features"]["buy_qty_window"] == .5
    assert online[-1]["features"]["midpoint"] == 101
    assert online[-1]["asof_ts"].startswith("2026-10-28")
    assert result["feature_sha256"] == replay_session(raw, session)["feature_sha256"]
    assert not list(tmp_path.glob(".replay-*"))


def test_future_events_do_not_change_earlier_features(capture, tmp_path):
    raw, session, emit, trade, depth, online, config = capture
    depth(); trade(1)
    first = tmp_path / "first.jsonl"
    replay_session(raw, session, output_path=first)
    prefix = first.read_bytes()
    trade(2); depth(12)
    second = tmp_path / "second.jsonl"
    replay_session(raw, session, output_path=second)
    assert second.read_bytes().startswith(prefix)


def test_cross_day_partitions_keep_application_sequence(capture):
    raw, session, emit, trade, depth, online, config = capture
    depth(); trade(1); depth(12); trade(2)
    before = replay_session(raw, session)
    for path in list(raw.glob("*.jsonl")):
        events = rows(path)
        rewrite(path, events[:-1])
        rewrite(path.with_name(path.name.replace("2026-10-28", "2026-10-29")), events[-1:])
    after = replay_session(raw, session)
    assert after["records"] == before["records"]
    assert after["feature_sha256"] == before["feature_sha256"]


@pytest.mark.parametrize("change", ["legacy", "missing", "duplicate", "reverse", "hash", "version",
                                    "policy", "wall_clock", "monotonic", "receipt", "receipt_wall", "previous_id",
                                    "depth_gap", "side", "trade_id", "crossed"])
def test_corrupt_selected_data_fails_without_published_output(capture, tmp_path, change):
    raw, session, emit, trade, depth, online, config = capture
    depth(); trade(1); trade(2)
    path = depth_file(raw)
    events = rows(path)
    quality = events[1]["data_quality"]
    if change == "legacy": quality.pop("ordering_version")
    elif change == "missing": quality["ingest_sequence"] += 1
    elif change == "duplicate": quality["ingest_sequence"] = 1
    elif change == "reverse": events.reverse()
    elif change == "hash": quality["feature_sha256"] = "0" * 64
    elif change == "version": quality["feature_version"] = "unknown"
    elif change == "policy": quality["feature_policy"]["stale_l2_ms"] += 1
    elif change == "wall_clock": quality["applied_ts"] = "2025-01-01T00:00:00Z"
    elif change == "monotonic": quality["applied_monotonic_ns"] = 1
    elif change == "receipt": events[1]["monotonic_ns"] = quality["applied_monotonic_ns"] + 1
    elif change == "receipt_wall": events[1]["received_ts"] = "2027-01-01T00:00:00Z"
    elif change == "previous_id": events[1]["previous_final_update_id"] = 0
    elif change == "depth_gap": events[1].update(first_update_id=20, final_update_id=21)
    elif change == "crossed": events[1]["bids"] = [["103", "1"]]
    else:
        path = trade_file(raw); events = rows(path)
        if change == "side": events[1]["trade_side"] = "sell"
        elif change == "trade_id": events[1]["trade_id"] = 1
    rewrite(path, events)
    original = {p.name: p.read_bytes() for p in raw.iterdir()}
    output = tmp_path / "features.jsonl"
    with pytest.raises((ValueError, OrderBookGap, SchemaValidationError)):
        replay_session(raw, session, output_path=output)
    assert not output.exists()
    assert not list(tmp_path.glob(".replay-*"))
    assert {p.name: p.read_bytes() for p in raw.iterdir()} == original


@pytest.mark.parametrize("fault", [b'{}', b'{broken}\n', b'\n', b'{"x":1,"x":2}\n', b'{"x":NaN}\n'])
def test_bad_json_and_incomplete_records_fail_globally(capture, fault):
    raw, session, emit, trade, depth, online, config = capture
    depth()
    with depth_file(raw).open("ab") as stream: stream.write(fault)
    with pytest.raises(ReplayError): replay_session(raw, session)


def test_bounds_counts_and_output_preservation(capture, tmp_path):
    raw, session, emit, trade, depth, online, config = capture
    depth(); trade(1)
    output = tmp_path / "features.jsonl"
    output.write_text("previous artifact")
    with pytest.raises(FileExistsError): replay_session(raw, session, output_path=output)
    assert output.read_text() == "previous artifact"
    with pytest.raises(ReplayError, match="outside"): replay_session(raw, session, output_path=raw / "output.jsonl")
    with pytest.raises(ReplayError, match="Oversized"): replay_session(raw, session, max_record_bytes=32)
    with pytest.raises(ReplayError, match="byte budget"): replay_session(raw, session, max_output_bytes=32)
    with pytest.raises(ReplayError, match="Expected"): replay_session(raw, session, expected={"trade": 99})
    with pytest.raises(ReplayError, match="not found"): replay_session(raw, "absent")


def test_input_mutation_and_new_file_are_not_accepted(capture, monkeypatch, tmp_path):
    raw, session, emit, trade, depth, online, config = capture
    depth(); trade(1)
    original = CausalFeaturePipeline.apply
    def mutate(self, event, **kwargs):
        result = original(self, event, **kwargs)
        if self.sequence == 2:
            with depth_file(raw).open("ab") as stream: stream.write(b"{}\n")
        return result
    monkeypatch.setattr(CausalFeaturePipeline, "apply", mutate)
    with pytest.raises(ReplayError): replay_session(raw, session, output_path=tmp_path / "out.jsonl")
    assert not (tmp_path / "out.jsonl").exists()


def test_input_symlink_and_inventory_cap(capture):
    raw, session, emit, trade, depth, online, config = capture
    depth()
    path = depth_file(raw); original = path.with_suffix(".saved")
    path.rename(original); path.symlink_to(original)
    with pytest.raises(ReplayError, match="regular file"): replay_session(raw, session)
    path.unlink(); original.rename(path)
    for day in range(1, 65):
        (raw / f"binance_btcusdt_trade_2025-01-{day:02}.jsonl").touch()
    with pytest.raises(ReplayError, match="64-file"): replay_session(raw, session)


def test_deadline_is_checked_while_scanning(capture, monkeypatch):
    raw, session, emit, trade, depth, online, config = capture
    depth(); trade(1)
    from signal_desk.replay import session as replay
    ticks = iter([0, 0, 2, 3, 4, 5])
    monkeypatch.setattr(replay.time, "monotonic", lambda: next(ticks))
    with pytest.raises(ReplayError, match="runtime budget"):
        replay_session(raw, session, max_runtime_seconds=1)


def test_book_growth_cap_fails_capture(capture):
    raw, session, emit, trade, depth, online, config = capture
    pipeline = config["_capture_features"]
    pipeline.policy["max_book_levels"] = 2
    event = map_depth_delta({"U": 11, "u": 11, "E": 1, "b": [["99", "1"]], "a": []})
    event["previous_final_update_id"] = 10
    with pytest.raises(ValueError, match="level cap"): emit(event)
    assert len(rows(depth_file(raw))) == 1


def test_stale_trade_or_book_is_unready(capture):
    raw, session, emit, trade, depth, online, config = capture
    depth(); trade(1)
    assert online[-1]["data_quality"]["ready"]
    trade(2, advance_ns=3_100_000_000)
    assert not online[-1]["data_quality"]["ready"]
    assert replay_session(raw, session)["ready_features"] == 1


def test_memory_does_not_scale_with_record_count(capture, tmp_path):
    raw, session, emit, trade, depth, online, config = capture
    depth()
    for number in range(1, 101): trade(number)
    small_raw = tmp_path / "small_raw"
    shutil.copytree(raw, small_raw)
    for number in range(101, 1001): trade(number)
    # Warm schema/regex caches on the short input. A one-time process-wide
    # pathlib intern-table resize can occur in either measured replay, so use
    # the lowest of three per-call peaks at each input size.
    replay_session(small_raw, session)
    def peak(directory):
        tracemalloc.start()
        replay_session(directory, session)
        _, result = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return result
    small = min(peak(small_raw) for _ in range(3))
    large = min(peak(raw) for _ in range(3))
    assert small < 1_000_000, small  # A polluted baseline must not mask growth.
    assert large < small + 1_000_000, (small, large)


def test_legacy_cli_reports_unsupported(capture):
    raw, session, emit, trade, depth, online, config = capture
    depth()
    path = depth_file(raw); events = rows(path)
    for event in events: event["data_quality"].pop("ordering_version")
    rewrite(path, events)
    result = subprocess.run([sys.executable, "-m", "signal_desk.replay.session",
                             "--raw-dir", str(raw), "--session-id", session],
                            text=True, capture_output=True)
    assert result.returncode == 2
    assert json.loads(result.stdout)["status"] == "unsupported"


def test_session_reset_isolated_from_other_records(capture):
    raw, session, emit, trade, depth, online, config = capture
    depth(); trade(1)
    first = replay_session(raw, session)
    emit(map_snapshot({"lastUpdateId": 10, "bids": [["100", "2"]], "asks": [["102", "1"]]},
                      received_ts="2026-10-28T00:00:00Z"))
    next_session = config["_capture_features"].session_id
    depth(); trade(1)
    assert next_session != session
    assert replay_session(raw, session)["feature_sha256"] == first["feature_sha256"]
    second = replay_session(raw, next_session)
    assert second["records"] == 3
    assert config["_capture_features"].features.trade_count == 1


def test_no_depth_bridge_is_not_accepted(capture):
    raw, session, emit, trade, depth, online, config = capture
    trade(1)
    with pytest.raises(ReplayError, match="no depth bridge"):
        replay_session(raw, session)


def test_racing_output_creation_does_not_overwrite(capture, monkeypatch, tmp_path):
    raw, session, emit, trade, depth, online, config = capture
    depth(); trade(1)
    from signal_desk.replay import session as replay
    original = replay.os.link
    output = tmp_path / "features.jsonl"
    def race(source, target):
        Path(target).write_bytes(b"another process")
        return original(source, target)
    monkeypatch.setattr(replay.os, "link", race)
    with pytest.raises(FileExistsError):
        replay_session(raw, session, output_path=output)
    assert output.read_bytes() == b"another process"
    assert not list(tmp_path.glob(".replay-*"))


def test_legacy_single_file_iterator_is_record_bounded(tmp_path):
    from signal_desk.storage.jsonl import iter_jsonl
    path = tmp_path / "input.jsonl"
    path.write_bytes(b'{"x":1}\n' + b'x' * 100)
    iterator = iter_jsonl(path, max_record_bytes=32)
    assert next(iterator) == {"x": 1}
    with pytest.raises(ValueError, match="Oversized"):
        next(iterator)


def test_actual_stream_buffer_capture_replays_in_application_order(tmp_path, monkeypatch):
    messages = [
        {"e": "trade", "T": 1, "t": 1, "p": "101", "q": "1", "m": False},
        {"e": "depthUpdate", "E": 1, "U": 9, "u": 10, "b": [], "a": []},
        {"e": "depthUpdate", "E": 1, "U": 11, "u": 11, "b": [["100", "3"]], "a": []},
        {"e": "trade", "T": 2, "t": 2, "p": "101", "q": "1", "m": True},
    ]
    class Socket:
        def __aiter__(self): return self
        async def __anext__(self):
            if messages: return json.dumps(messages.pop(0))
            await asyncio.Event().wait()
    async def snapshot(*args, **kwargs):
        return {"lastUpdateId": 10, "bids": [["100", "2"]], "asks": [["102", "1"]]}
    config = {"exchange": {"symbol": "BTCUSDT", "endpoints": {"rest_base_url": "unused"},
                           "market_data": {"snapshot_limit": 5000}},
              "storage": {"raw_path": str(tmp_path / "raw")}}
    monkeypatch.setattr(collector, "fetch_snapshot_async", snapshot)
    monkeypatch.setattr(collector, "write_status", lambda *args, **kwargs: None)
    online = []
    digest = collector.feature_digest
    def remember(feature):
        online.append(feature)
        return digest(feature)
    monkeypatch.setattr(collector, "feature_digest", remember)
    stats = asyncio.run(collector.collect_connected_stream(Socket(), config, 4))
    output = tmp_path / "features.jsonl"
    result = replay_session(tmp_path / "raw", stats["session_id"], output_path=output,
                            expected={"book_snapshot": 1, "book_delta": 1, "trade": 2})
    assert stats["last_ingest_sequence"] == result["capture_hashes_verified"] == 4
    assert rows(output) == online
    assert stats["stale_depth_events"] == 1
    depth_rows = rows(depth_file(tmp_path / "raw"))
    trade_rows = rows(trade_file(tmp_path / "raw"))
    assert trade_rows[0]["monotonic_ns"] < depth_rows[0]["monotonic_ns"]
    assert trade_rows[0]["data_quality"]["ingest_sequence"] == 2
