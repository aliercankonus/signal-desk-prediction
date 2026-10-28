"""Local regressions for a proposed, never-executed VPS soak procedure."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts/review/soak_gates.py"
SCRIPT = ROOT / "scripts/review/vps-soak-91cd925.sh"
SID = "a" * 32


def gates():
    spec = importlib.util.spec_from_file_location("soak_gates", HELPER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def evidence(tmp_path, *, depth=2, trade=1, reconnect=0, reason="max_run_seconds_reached"):
    raw = tmp_path / "raw"
    raw.mkdir()
    path = raw / "binance_btcusdt_depth_2026-10-28.jsonl"
    old = b'{"legacy":true}\n'
    events = ["book_snapshot"] + ["book_delta"] * depth + ["trade"] * trade
    records = [(event, json.dumps({"event_type": event, "data_quality": {
        "collector_session_id": SID, "ordering_version": "session-applied-v1", "ingest_sequence": n,
    }}).encode() + b"\n") for n, event in enumerate(events, 1)]
    path.write_bytes(old + b"".join(data for event, data in records if event != "trade"))
    (raw / "binance_btcusdt_trade_2026-10-28.jsonl").write_bytes(
        b"".join(data for event, data in records if event == "trade"))
    pre = {"files": {path.name: {"size": len(old)}}}
    status = {"status": "STOPPED", "reason": reason, "mode": "paper", "execution_enabled": False,
              "session_id": SID, "gap_count": 0, "reconnect_count": reconnect,
              "total_written_events": len(events), "total_depth_events": depth,
              "total_trade_events": trade}
    stopped = {k: status[k] for k in ("status", "reason", "session_id", "gap_count",
               "reconnect_count", "total_written_events", "total_depth_events", "total_trade_events")}
    state = {"Status": "exited", "ExitCode": 0, "OOMKilled": False}
    stats = '{"MemUsage":"16MiB / 512MiB"}\n'
    return raw, pre, status, json.dumps(stopped) + "\n", state, stats


def test_summarize_counts_only_new_bytes_and_verifies_duration_stop(tmp_path):
    raw, pre, status, log, state, stats = evidence(tmp_path)
    result = gates().summarize(raw, pre, status, log, state, stats)
    assert result["sessions"] == [{"session_id": SID, "book_snapshot": 1,
                                   "book_delta": 2, "trade": 1, "records": 4}]
    assert result["totals"]["records"] == 4


@pytest.mark.parametrize("field,value", [("reason", "signal_received"), ("reconnect_count", 1),
                                         ("gap_count", 1), ("execution_enabled", True),
                                         ("total_written_events", 5)])
def test_summarize_rejects_failed_stop_and_counter_or_paper_mismatch(tmp_path, field, value):
    raw, pre, status, log, state, stats = evidence(tmp_path)
    status[field] = value
    with pytest.raises(ValueError):
        gates().summarize(raw, pre, status, log, state, stats)


def test_summarize_rejects_incomplete_appended_record(tmp_path):
    raw, pre, status, log, state, stats = evidence(tmp_path)
    path = next(raw.iterdir())
    path.write_bytes(path.read_bytes()[:-1])
    with pytest.raises(ValueError, match="line|record"):
        gates().summarize(raw, pre, status, log, state, stats)


def test_summarize_rejects_multiple_capture_sessions(tmp_path):
    raw, pre, status, log, state, stats = evidence(tmp_path)
    path = raw / "binance_btcusdt_depth_2026-10-28.jsonl"
    with path.open("ab") as stream:
        stream.write(json.dumps({"event_type": "book_snapshot", "data_quality": {
            "collector_session_id": "b" * 32, "ordering_version": "session-applied-v1",
            "ingest_sequence": 1}}).encode() + b"\n")
    with pytest.raises(ValueError, match="session|count"):
        gates().summarize(raw, pre, status, log, state, stats)


def test_verify_session_checks_counts_hashes_and_matching_replays():
    expected = {"session_id": SID, "book_snapshot": 1, "book_delta": 2, "trade": 1, "records": 4}
    counts = {key: expected[key] for key in ("book_snapshot", "book_delta", "trade")}
    file = {"file": "binance_btcusdt_depth_2026-10-28.jsonl", "sha256": "c" * 64,
            "bytes": 123, "lines": 5, "selected_records": 4}
    audit = {"status": "ok", "session_id": SID, "counts": counts, "selected_records": 4, "files": [file]}
    replay = {"status": "ok", "session_id": SID, "counts": counts, "records": 4,
              "last_ingest_sequence": 4, "expected_counts_checked": True,
              "capture_hashes_verified": 4, "ready_features": 1, "feature_sha256": "d" * 64,
              "files": [file]}
    manifest = {file["file"]: file["sha256"]}
    assert gates().verify_session(expected, audit, [replay, replay], manifest)["feature_sha256"] == "d" * 64
    for bad in ({**replay, "ready_features": 0}, {**replay, "capture_hashes_verified": 3},
                {**replay, "feature_sha256": "e" * 64}):
        with pytest.raises(ValueError):
            gates().verify_session(expected, audit, [replay, bad], manifest)


def test_orchestrator_is_review_only_and_reuses_exact_artifacts():
    text = SCRIPT.read_text()
    for fragment in ("--max-run-seconds 3600", "--restart no", "--memory 512m", "--cpus 0.75",
                     "--pids-limit 64", "timeout 3900s docker wait", "--network none",
                     "--max-runtime-seconds 3300", "verify-prefix", "raw-pre-capture.json",
                     "candidate-image-id.txt", "candidate-config.sha256", "active-inputs.sha256",
                     "--mode continuous", "docker stats --no-stream", "SOAK_OK"):
        assert fragment in text
    for prohibited in ("docker build", "git clone", "prepare-host-release.sh", "docker rm -f"):
        assert prohibited not in text
    assert "docker run -d" in text and '"$IMAGE_ID"' in text
    assert subprocess.run(["bash", "-n", str(SCRIPT)]).returncode == 0


def test_helper_cli_exclusive_private_output(tmp_path):
    raw, pre, status, log, state, stats = evidence(tmp_path)
    for name, value in (("pre", pre), ("status", status), ("state", state)):
        (tmp_path / f"{name}.json").write_text(json.dumps(value))
    (tmp_path / "log.txt").write_text(log)
    (tmp_path / "stats.jsonl").write_text(stats)
    output = tmp_path / "summary.json"
    args = [sys.executable, str(HELPER), "summarize", "--raw-dir", str(raw),
            "--pre-inventory", str(tmp_path / "pre.json"), "--status", str(tmp_path / "status.json"),
            "--log", str(tmp_path / "log.txt"), "--state", str(tmp_path / "state.json"),
            "--stats", str(tmp_path / "stats.jsonl"), "--output", str(output)]
    first = subprocess.run(args, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    assert output.stat().st_mode & 0o777 == 0o600
    assert subprocess.run(args, capture_output=True).returncode != 0


def test_raw_manifest_rejects_new_file_after_replays(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    old = raw / "binance_btcusdt_depth_2026-10-28.jsonl"
    old.write_bytes(b"old\n")
    manifest = {old.name: "a" * 64}
    assert gates().verify_raw_set(raw, manifest) == 1
    (raw / "binance_btcusdt_trade_2026-10-28.jsonl").write_bytes(b"new\n")
    with pytest.raises(ValueError, match="file set"):
        gates().verify_raw_set(raw, manifest)


def test_protected_config_is_in_agent_mount_overlap_check():
    text = SCRIPT.read_text()
    assert '"$EVIDENCE_PARENT" "$PRIOR" "$SCRIPT_DIR" "$CONFIG_DIR"' in text
    assert 'protected = [pathlib.Path(p).resolve() for p in (evidence, prior, staging, config)]' in text


def test_inconclusive_one_off_cleanup_warns_operator():
    text = SCRIPT.read_text()
    cleanup = text.split("run_readonly() {", 1)[1].split("# All sessions found", 1)[0]
    assert "Candidate read-only container identity unconfirmed" in cleanup
    assert "Candidate read-only container stop unconfirmed" in cleanup
