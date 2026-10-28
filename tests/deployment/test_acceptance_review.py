"""Local-only regressions for the unexecuted VPS acceptance proposal."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import unittest


def gates():
    path = Path(__file__).resolve().parents[2] / "scripts/review/acceptance_gates.py"
    assert path.is_file(), "acceptance_gates.py is required"
    spec = spec_from_file_location("acceptance_gates", path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_inventory_records_all_existing_raw_files_and_hashes(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "depth.jsonl").write_bytes(b"old-depth\n")
    (raw / "trade.jsonl").write_bytes(b"old-trade\n")
    snapshot = gates().inventory_raw(raw)
    assert set(snapshot["files"]) == {"depth.jsonl", "trade.jsonl"}
    assert snapshot["files"]["depth.jsonl"]["size"] == len(b"old-depth\n")
    assert snapshot["files"]["depth.jsonl"]["sha256"] == hashlib.sha256(b"old-depth\n").hexdigest()


def test_prefix_check_allows_appends_and_new_files(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    original = raw / "depth.jsonl"
    original.write_bytes(b"original\n")
    snapshot = gates().inventory_raw(raw)
    with original.open("ab") as stream:
        stream.write(b"appended\n")
    (raw / "trade.jsonl").write_bytes(b"new\n")
    result = gates().verify_raw_prefix(raw, snapshot)
    assert result["original_files_checked"] == 1
    assert result["appended_files"] == ["depth.jsonl"]
    assert result["new_files"] == ["trade.jsonl"]


def test_prefix_check_rejects_truncated_original(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    original = raw / "depth.jsonl"
    original.write_bytes(b"original\n")
    snapshot = gates().inventory_raw(raw)
    original.write_bytes(b"short")
    with unittest.TestCase().assertRaisesRegex(ValueError, "shrank"):
        gates().verify_raw_prefix(raw, snapshot)


def test_prefix_check_rejects_modified_prefix_even_if_appended(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    original = raw / "depth.jsonl"
    original.write_bytes(b"original\n")
    snapshot = gates().inventory_raw(raw)
    original.write_bytes(b"Xriginal\nappended\n")
    with unittest.TestCase().assertRaisesRegex(ValueError, "prefix changed"):
        gates().verify_raw_prefix(raw, snapshot)


def test_prefix_check_rejects_missing_original(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    original = raw / "depth.jsonl"
    original.write_bytes(b"original\n")
    snapshot = gates().inventory_raw(raw)
    original.unlink()
    with unittest.TestCase().assertRaisesRegex(ValueError, "missing or replaced"):
        gates().verify_raw_prefix(raw, snapshot)


def test_prefix_check_rejects_replaced_inode_with_identical_bytes(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    original = raw / "depth.jsonl"
    original.write_bytes(b"original\n")
    snapshot = gates().inventory_raw(raw)
    replacement = raw / "replacement"
    replacement.write_bytes(b"original\n")
    replacement.replace(original)
    with unittest.TestCase().assertRaisesRegex(ValueError, "identity changed"):
        gates().verify_raw_prefix(raw, snapshot)


def test_inventory_and_prefix_cli_save_private_evidence(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    path = raw / "depth.jsonl"
    path.write_bytes(b"original\n")
    tool = Path(__file__).resolve().parents[2] / "scripts/review/acceptance_gates.py"
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    first = subprocess.run([sys.executable, str(tool), "inventory", "--raw-dir", str(raw),
                            "--output", str(before)], capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    assert json.loads(before.read_text())["files"]["depth.jsonl"]["size"] == len(b"original\n")
    with path.open("ab") as stream:
        stream.write(b"appended\n")
    second = subprocess.run([sys.executable, str(tool), "verify-prefix", "--raw-dir", str(raw),
                             "--inventory", str(before), "--output", str(after)], capture_output=True, text=True)
    assert second.returncode == 0, second.stderr
    assert json.loads(after.read_text())["appended_files"] == ["depth.jsonl"]


def test_capture_gate_rejects_zero_trades():
    summary = {"status": "ok", "session_id": "a" * 32, "written_events": 1000,
               "last_ingest_sequence": 1000, "depth_events": 999, "trade_events": 0,
               "gap_count": 0, "ordering_version": "session-applied-v1"}
    with unittest.TestCase().assertRaisesRegex(ValueError, "positive depth and trade"):
        gates().check_capture(summary, "b" * 32)


def test_capture_gate_rejects_zero_depth():
    summary = {"status": "ok", "session_id": "a" * 32, "written_events": 1000,
               "last_ingest_sequence": 1000, "depth_events": 0, "trade_events": 999,
               "gap_count": 0, "ordering_version": "session-applied-v1"}
    with unittest.TestCase().assertRaisesRegex(ValueError, "positive depth and trade"):
        gates().check_capture(summary, "b" * 32)


def test_capture_gate_accepts_positive_depth_and_trade():
    summary = {"status": "ok", "session_id": "a" * 32, "written_events": 1000,
               "last_ingest_sequence": 1000, "depth_events": 500, "trade_events": 499,
               "gap_count": 0, "ordering_version": "session-applied-v1"}
    result = gates().check_capture(summary, "b" * 32)
    assert result == {"session_id": "a" * 32, "book_snapshot": 1,
                      "book_delta": 500, "trade": 499, "records": 1000}


def replay_evidence():
    capture = {"session_id": "a" * 32, "book_snapshot": 1,
               "book_delta": 500, "trade": 499, "records": 1000}
    counts = {"book_snapshot": 1, "book_delta": 500, "trade": 499}
    file = {"file": "depth.jsonl", "sha256": "a" * 64, "bytes": 42,
            "lines": 2, "selected_records": 2}
    audit = {"status": "ok", "session_id": capture["session_id"],
             "counts": counts, "selected_records": 1000, "files": [file]}
    replay = {"status": "ok", "session_id": capture["session_id"],
              "counts": counts, "records": 1000, "expected_counts_checked": True,
              "capture_hashes_verified": 1000, "last_ingest_sequence": 1000,
              "ready_features": 1, "feature_sha256": "b" * 64, "files": [file]}
    return capture, audit, [replay.copy(), replay.copy()], {"depth.jsonl": "a" * 64}


def test_replay_gate_rejects_zero_ready_features_in_either_run():
    capture, audit, runs, manifest = replay_evidence()
    for index in (0, 1):
        changed = [run.copy() for run in runs]
        changed[index]["ready_features"] = 0
        with unittest.TestCase().assertRaisesRegex(ValueError, "positive ready_features"):
            gates().check_replays(audit, changed, capture, manifest)


def test_replay_gate_accepts_two_ready_matching_results():
    capture, audit, runs, manifest = replay_evidence()
    result = gates().check_replays(audit, runs, capture, manifest)
    assert result == {"feature_sha256": "b" * 64, "files_checked": 1,
                      "ready_features": [1, 1]}


def test_replay_gate_rejects_hash_disagreement():
    capture, audit, runs, manifest = replay_evidence()
    runs[1]["feature_sha256"] = "c" * 64
    with unittest.TestCase().assertRaisesRegex(ValueError, "digests disagree"):
        gates().check_replays(audit, runs, capture, manifest)


def test_replay_gate_rejects_missing_capture_hash_verification():
    capture, audit, runs, manifest = replay_evidence()
    runs[1]["capture_hashes_verified"] = 999
    with unittest.TestCase().assertRaisesRegex(ValueError, "every expected record"):
        gates().check_replays(audit, runs, capture, manifest)


def test_capture_cli_checks_state_stats_and_writes_counts(tmp_path):
    tool = Path(__file__).resolve().parents[2] / "scripts/review/acceptance_gates.py"
    summary = {"status": "ok", "session_id": "a" * 32, "written_events": 1000,
               "last_ingest_sequence": 1000, "depth_events": 500, "trade_events": 499,
               "gap_count": 0, "ordering_version": "session-applied-v1"}
    (tmp_path / "capture-state.json").write_text(json.dumps({"Status": "exited", "ExitCode": 0, "OOMKilled": False}))
    (tmp_path / "capture.log").write_text(json.dumps(summary) + "\n")
    (tmp_path / "collector-stats.jsonl").write_text(json.dumps({"MemUsage": "12MiB / 512MiB"}) + "\n")
    result = subprocess.run([sys.executable, str(tool), "check-capture", "--evidence-dir", str(tmp_path),
                             "--previous-session", "b" * 32], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads((tmp_path / "capture-summary.json").read_text())["trade"] == 499


def test_replay_cli_verifies_both_ready_results(tmp_path):
    capture, audit, runs, manifest = replay_evidence()
    (tmp_path / "capture-summary.json").write_text(json.dumps(capture))
    (tmp_path / "raw-audit.json").write_text(json.dumps(audit))
    for number, value in enumerate(runs, 1):
        (tmp_path / f"replay-{number}.json").write_text(json.dumps(value))
    (tmp_path / "raw-before.sha256").write_text(next(iter(manifest.values())) + "  /data/raw/depth.jsonl\n")
    tool = Path(__file__).resolve().parents[2] / "scripts/review/acceptance_gates.py"
    result = subprocess.run([sys.executable, str(tool), "check-replays", "--evidence-dir", str(tmp_path)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads((tmp_path / "replay-check.json").read_text())["ready_features"] == [1, 1]


def test_one_off_validation_and_replay_have_limits_and_time_budgets():
    script = (Path(__file__).resolve().parents[2] / "scripts/review/vps-acceptance-91cd925.sh").read_text()
    assert "run_bounded()" in script
    for option in ("--memory 512m", "--cpus 0.75", "--pids-limit 64", "timeout --signal=INT --kill-after=20s"):
        assert option in script
    for invocation in ("run_bounded 180s validate", "run_bounded 600s pytest",
                       "run_bounded 300s audit", "run_bounded 600s replay-$run"):
        assert invocation in script


def test_pinned_candidate_suite_stays_at_140_tests():
    script = (Path(__file__).resolve().parents[2] / "scripts/review/vps-acceptance-91cd925.sh").read_text()
    assert "140 passed" in script


def test_review_gate_is_staged_with_script_not_expected_in_pinned_candidate():
    script = (Path(__file__).resolve().parents[2] / "scripts/review/vps-acceptance-91cd925.sh").read_text()
    assert 'GATES=$SCRIPT_DIR/acceptance_gates.py' in script
    assert '$RELEASE/scripts/review/acceptance_gates.py' not in script


def test_replay_manifest_covers_all_jsonl_files_not_only_btc_patterns():
    script = (Path(__file__).resolve().parents[2] / "scripts/review/vps-acceptance-91cd925.sh").read_text()
    assert 'raw_files=( "$RAW_DIR"/*.jsonl )' in script


def test_one_off_failure_cleanup_calls_are_bounded():
    script = (Path(__file__).resolve().parents[2] / "scripts/review/vps-acceptance-91cd925.sh").read_text()
    assert 'timeout 20s docker stop --time 10 "$name"' in script
    assert 'timeout 20s docker rm -f "$name"' in script


def test_failed_capture_attempts_prefix_verification_after_stop():
    script = (Path(__file__).resolve().parents[2] / "scripts/review/vps-acceptance-91cd925.sh").read_text()
    cleanup = script.split("cleanup_on_failure() {", 1)[1].split("trap cleanup_on_failure EXIT", 1)[0]
    assert 'verify-prefix --raw-dir "$RAW_DIR"' in cleanup
