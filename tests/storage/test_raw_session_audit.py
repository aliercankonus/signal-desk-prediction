import hashlib
import json
from pathlib import Path

import pytest

from signal_desk.collector.binance_mapping import map_snapshot, map_depth_delta, map_trade
from signal_desk.tools import audit_raw


SESSION = "fixture-session"


def tagged(event, session=SESSION):
    event["data_quality"]["collector_session_id"] = session
    return event


def snapshot():
    return tagged(map_snapshot({"lastUpdateId": 100, "bids": [["10", "1"]], "asks": [["11", "1"]]}))


def delta(first=101, final=102, previous=100):
    event = tagged(map_depth_delta({"U": first, "u": final, "E": 1, "b": [["10", "2"]], "a": []}))
    event["previous_final_update_id"] = previous
    return event


def trade(number=1):
    return tagged(map_trade({"e": "trade", "E": 1, "T": 1, "t": number, "p": "10", "q": "1", "m": False}))


def write(path, events):
    data = b"".join((json.dumps(e, sort_keys=True) + "\n").encode() for e in events)
    path.write_bytes(data)
    return data


def test_valid_session_counts_and_hash_without_modifying_inputs(tmp_path):
    d = write(tmp_path / "depth.jsonl", [snapshot(), delta()])
    t = write(tmp_path / "trade.jsonl", [trade(1), trade(3)])
    result = audit_raw.audit_session(tmp_path, SESSION, expected={"book_snapshot": 1, "book_delta": 1, "trade": 2})
    assert result["status"] == "ok"
    assert result["selected_records"] == 4
    assert result["last_depth_update_id"] == 102
    assert result["files"][0]["sha256"] == hashlib.sha256(d).hexdigest()
    assert result["files"][1]["sha256"] == hashlib.sha256(t).hexdigest()
    assert (tmp_path / "depth.jsonl").read_bytes() == d
    assert (tmp_path / "trade.jsonl").read_bytes() == t
    assert len(list(tmp_path.iterdir())) == 2  # Audit creates no output files.


def test_other_sessions_are_not_counted(tmp_path):
    write(tmp_path / "depth.jsonl", [tagged(snapshot(), "other"), snapshot(), delta()])
    result = audit_raw.audit_session(tmp_path, SESSION)
    assert result["status"] == "ok"
    assert result["selected_records"] == 2


@pytest.mark.parametrize("events,error", [
    ([snapshot(), delta(103, 104)], "depth_gap"),
    ([snapshot(), delta(previous=99)], "previous_depth_id"),
    ([snapshot(), delta(), delta()], "duplicate_or_old_depth"),
    ([delta()], "depth_without_snapshot"),
])
def test_depth_faults_are_not_accepted(tmp_path, events, error):
    write(tmp_path / "depth.jsonl", events)
    result = audit_raw.audit_session(tmp_path, SESSION)
    assert result["status"] == "failed"
    assert result["error_counts"][error] >= 1


def test_duplicate_trade_is_detected(tmp_path):
    write(tmp_path / "depth.jsonl", [snapshot()])
    write(tmp_path / "trade.jsonl", [trade(), trade()])
    result = audit_raw.audit_session(tmp_path, SESSION)
    assert result["error_counts"]["duplicate_or_reordered_trade"] == 1


def test_json_corruption_is_reported_even_outside_known_session(tmp_path):
    (tmp_path / "depth.jsonl").write_bytes(b"broken json\n")
    result = audit_raw.audit_session(tmp_path, SESSION)
    assert result["error_counts"]["json"] == 1


def test_unterminated_tail_fails_closed(tmp_path):
    (tmp_path / "depth.jsonl").write_bytes(json.dumps(snapshot()).encode())
    result = audit_raw.audit_session(tmp_path, SESSION)
    assert result["error_counts"]["unterminated_record"] == 1


def test_oversized_line_is_drained_and_hashed_in_bounded_chunks(tmp_path):
    path = tmp_path / "depth.jsonl"
    content = b"x" * 10000 + b"\n" + (json.dumps(snapshot()) + "\n").encode()
    path.write_bytes(content)
    result = audit_raw.audit_session(tmp_path, SESSION, max_record_bytes=2048)
    assert result["error_counts"]["oversized_record"] == 1
    assert result["counts"]["book_snapshot"] == 1
    assert result["files"][0]["bytes"] == len(content)
    assert result["files"][0]["sha256"] == hashlib.sha256(content).hexdigest()


def test_wrong_expected_count_and_missing_session_fail(tmp_path):
    write(tmp_path / "depth.jsonl", [snapshot()])
    result = audit_raw.audit_session(tmp_path, SESSION, expected={"book_snapshot": 2})
    assert result["error_counts"]["count_mismatch"] == 1
    missing = audit_raw.audit_session(tmp_path, "absent")
    assert missing["error_counts"]["session_not_found"] == 1


def test_semantic_and_schema_errors_remain_failures(tmp_path):
    event = trade()
    event["trade_side"] = "sell"
    invalid = trade(2)
    invalid["symbol"] = "WRONG"
    write(tmp_path / "depth.jsonl", [snapshot()])
    write(tmp_path / "trade.jsonl", [event, invalid])
    result = audit_raw.audit_session(tmp_path, SESSION)
    assert result["error_counts"]["event_semantics"] == 1
    assert result["error_counts"]["schema"] == 1


def test_input_change_during_scan_is_reported(monkeypatch, tmp_path):
    path = tmp_path / "depth.jsonl"
    write(path, [snapshot()])
    original = audit_raw.validate_json

    def changing_validator(*args):
        with path.open("ab") as output:
            output.write(b"\n")
        original(*args)

    monkeypatch.setattr(audit_raw, "validate_json", changing_validator)
    result = audit_raw.audit_session(tmp_path, SESSION)
    assert result["error_counts"]["file_changed"] == 1
    assert result["error_counts"]["raw_inventory_changed"] == 1


def test_errors_are_counted_but_samples_are_bounded(tmp_path):
    (tmp_path / "depth.jsonl").write_bytes(b"broken\n" * 20)
    result = audit_raw.audit_session(tmp_path, SESSION)
    assert result["error_counts"]["json"] == 20
    assert len(result["error_samples"]) == 5
