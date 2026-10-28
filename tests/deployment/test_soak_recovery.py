"""Recovery-only gates on synthetic, existing ordered capture evidence."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts/review/soak_recovery_gates.py"
SCRIPT = ROOT / "scripts/review/vps-recover-soak-91cd925.sh"
SID = "cb8a0767d7284b8aaa3d09fbca7095f2"


def recovery():
    sys.path.insert(0, str(HELPER.parent))
    try:
        spec = importlib.util.spec_from_file_location("soak_recovery_gates", HELPER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def existing_capture(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    depth = raw / "binance_btcusdt_depth_2026-10-28.jsonl"
    old = b'{"legacy":true}\n'
    events = [("book_snapshot", 1), ("book_delta", 2), ("trade", 3)]
    encoded = [(kind, json.dumps({"event_type": kind, "data_quality": {
        "collector_session_id": SID, "ordering_version": "session-applied-v1",
        "ingest_sequence": sequence}}).encode() + b"\n") for kind, sequence in events]
    depth.write_bytes(old + b"".join(line for kind, line in encoded if kind != "trade"))
    trade = raw / "binance_btcusdt_trade_2026-10-28.jsonl"
    trade.write_bytes(b"".join(line for kind, line in encoded if kind == "trade"))
    info = depth.stat()
    pre = {"files": {depth.name: {"size": len(old), "sha256": hashlib.sha256(old).hexdigest(),
                                  "device": info.st_dev, "inode": info.st_ino}}}
    return raw, pre


def test_derive_requires_original_prefix_and_exact_existing_session(tmp_path):
    raw, pre = existing_capture(tmp_path)
    result = recovery().derive(raw, pre, SID)
    assert result["session_id"] == SID
    assert result["counts"] == {"book_snapshot": 1, "book_delta": 1, "trade": 1}
    assert result["records"] == 3
    assert result["counts_origin"] == "raw_appended_bytes_not_independent_completion_evidence"
    assert result["soak_acceptance"] is False


def test_derive_rejects_wrong_session_and_changed_original_prefix(tmp_path):
    raw, pre = existing_capture(tmp_path)
    with pytest.raises(ValueError):
        recovery().derive(raw, pre, "a" * 32)
    path = raw / "binance_btcusdt_depth_2026-10-28.jsonl"
    with path.open("r+b") as stream:
        stream.write(b"X")
    with pytest.raises(ValueError):
        recovery().derive(raw, pre, SID)


def test_derive_refuses_incomplete_tail_and_multiple_new_sessions(tmp_path):
    raw, pre = existing_capture(tmp_path)
    trade = raw / "binance_btcusdt_trade_2026-10-28.jsonl"
    trade.write_bytes(trade.read_bytes()[:-1])
    with pytest.raises(ValueError):
        recovery().derive(raw, pre, SID)
    trade.write_bytes(trade.read_bytes() + b"\n")
    depth = raw / "binance_btcusdt_depth_2026-10-28.jsonl"
    with depth.open("ab") as stream:
        stream.write(json.dumps({"event_type": "book_snapshot", "data_quality": {
            "collector_session_id": "a" * 32, "ordering_version": "session-applied-v1",
            "ingest_sequence": 1}}).encode() + b"\n")
    with pytest.raises(ValueError):
        recovery().derive(raw, pre, SID)


def test_derive_rejects_oversized_raw_file_set_before_counting(tmp_path):
    raw, pre = existing_capture(tmp_path)
    for day in range(1, 65):
        (raw / f"binance_btcusdt_depth_2026-11-{day:02}.jsonl").write_bytes(b"")
    with pytest.raises(ValueError, match="file cap"):
        recovery().derive(raw, pre, SID)


def test_derive_rejects_large_raw_file_before_scanning(tmp_path):
    raw, pre = existing_capture(tmp_path)
    trade = raw / "binance_btcusdt_trade_2026-10-28.jsonl"
    with trade.open("r+b") as stream:
        stream.truncate(8 * 1024 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="size cap"):
        recovery().derive(raw, pre, SID)


def test_derive_rejects_large_non_jsonl_pre_inventory_before_prefix_hash(tmp_path, monkeypatch):
    raw, pre = existing_capture(tmp_path)
    auxiliary = raw / "auxiliary.bin"
    with auxiliary.open("wb") as stream:
        stream.truncate(8 * 1024 * 1024 * 1024 + 1)
    info = auxiliary.stat()
    pre["files"][auxiliary.name] = {"size": info.st_size, "sha256": "0" * 64,
                                    "device": info.st_dev, "inode": info.st_ino}
    module = recovery()
    def unexpected_prefix(*args):
        raise AssertionError("Unbounded prefix verifier was called")
    monkeypatch.setattr(module, "verify_raw_prefix", unexpected_prefix)
    with pytest.raises(ValueError, match="inventory size cap"):
        module.derive(raw, pre, SID)


def test_verification_is_diagnostic_not_soak_acceptance(tmp_path):
    raw, pre = existing_capture(tmp_path)
    derived = recovery().derive(raw, pre, SID)
    files = [{"file": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
              "bytes": p.stat().st_size, "lines": len(p.read_bytes().splitlines()),
              "selected_records": 2 if "depth" in p.name else 1}
             for p in sorted(raw.glob("*.jsonl"))]
    counts = derived["counts"]
    audit = {"status": "ok", "session_id": SID, "counts": counts,
             "selected_records": 3, "files": files}
    replay = {"status": "ok", "session_id": SID, "counts": counts,
              "records": 3, "last_ingest_sequence": 3,
              "expected_counts_checked": True, "capture_hashes_verified": 3,
              "ready_features": 1, "feature_sha256": "a" * 64, "files": files}
    manifest = {item["file"]: item["sha256"] for item in files}
    checked = recovery().verify(derived, audit, [replay, replay], manifest, raw)
    assert checked["diagnostic_status"] == "stored_session_audit_replay_matched"
    assert checked["soak_acceptance"] is False
    assert checked["independent_completion_verified"] is False
    with pytest.raises(ValueError):
        recovery().verify(derived, audit, [replay, {**replay, "ready_features": 0}], manifest, raw)


def test_manifest_parser_bounds_bytes_and_pins_raw_directory(tmp_path):
    raw, _ = existing_capture(tmp_path)
    manifest = tmp_path / "manifest"
    manifest.write_bytes(b"x" * (4 * 1024 * 1024 + 1))
    with pytest.raises(ValueError, match="byte cap"):
        recovery().parse_raw_manifest(manifest, raw)
    manifest.write_text("a" * 64 + "  /unrelated/binance_btcusdt_depth_2026-10-28.jsonl\n")
    with pytest.raises(ValueError, match="path"):
        recovery().parse_raw_manifest(manifest, raw)


def test_original_evidence_set_detects_added_file(tmp_path):
    original = tmp_path / "original"
    original.mkdir()
    (original / "raw-pre-capture.json").write_bytes(b"{}\n")
    manifest = tmp_path / "original.sha256"
    digest = hashlib.sha256(b"{}\n").hexdigest()
    manifest.write_text(f"{digest}  {original}/raw-pre-capture.json\n")
    recovery().verify_original_evidence(original, manifest)
    (original / "new-failure.log").write_bytes(b"changed")
    with pytest.raises(ValueError, match="file set"):
        recovery().verify_original_evidence(original, manifest)


def test_original_evidence_atime_is_not_mutation(tmp_path):
    original = tmp_path / "original"
    original.mkdir()
    item = original / "capture.log"
    item.write_bytes(b"unchanged")
    manifest = tmp_path / "original.sha256"
    manifest.write_text(f"{hashlib.sha256(b'unchanged').hexdigest()}  {item}\n")
    info = item.stat()
    os.utime(item, ns=(1_000_000_000, info.st_mtime_ns))
    recovery().verify_original_evidence(original, manifest)


def test_aggregate_record_limit_covers_all_sessions_before_count(tmp_path):
    raw, pre = existing_capture(tmp_path)
    with pytest.raises(ValueError, match="aggregate record cap"):
        recovery().check_aggregate_limit(raw, pre, limit=2)


def test_freeze_raw_and_verify_are_bounded_and_detect_mutation(tmp_path):
    raw, _ = existing_capture(tmp_path)
    manifest = tmp_path / "raw.sha256"
    recovery().freeze_raw(raw, manifest)
    parsed = recovery().parse_raw_manifest(manifest, raw)
    recovery().verify_current_raw(raw, parsed)
    trade = raw / "binance_btcusdt_trade_2026-10-28.jsonl"
    with trade.open("ab") as stream:
        stream.write(b"mutated\n")
    with pytest.raises(ValueError):
        recovery().verify_current_raw(raw, parsed)


def test_review_script_has_no_new_capture_or_deletion_and_is_syntax_valid():
    text = SCRIPT.read_text()
    assert SID in text
    for prohibited in ("--mode continuous", "--max-run-seconds", "docker build", "docker rm", "--rm",
                       "prepare-host-release.sh", "git clone", "docker compose up", "docker volume rm"):
        assert prohibited not in text
    assert "--network none" in text and "--read-only" in text
    assert "--memory 768m" in text and "--pids-limit 64" in text
    assert "RECOVERY_AGENT_NAME_FILTER" in text
    assert "Evidence parent overlaps release, active checkout or raw volume" in text
    assert "RECOVERY_PRIOR_EVIDENCE" in text and "RECOVERY_CONFIG_DIR" in text
    assert "RECOVERY_EXPECTED_ACTIVE_HEAD" in text
    assert "RECOVERY_EXPECTED_CANDIDATE_APPROVAL_SHA256" in text
    assert "ps -eo args=" in text
    assert "--cidfile" in text and "CURRENT_CIDFILE" in text
    assert "verify-original" in text
    assert "freeze-raw" in text and "verify-raw" in text
    assert subprocess.run(["bash", "-n", str(SCRIPT)], check=False).returncode == 0
