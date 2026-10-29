"""Synthetic-only evidence and exact-byte COPY gate contract."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

import pytest

from tests.deployment.test_soak_recovery import existing_capture, recovery, SID

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts/review/research_copy_gates.py"


def gate():
    sys.path.insert(0, str(HELPER.parent))
    try:
        spec = importlib.util.spec_from_file_location("research_copy_gates", HELPER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def evidence(tmp_path):
    raw, pre = existing_capture(tmp_path)
    for kind in ("depth", "trade"):
        (raw / f"binance_btcusdt_{kind}_2026-10-29.jsonl").write_bytes(b'')
    original = tmp_path / "original"
    original.mkdir()
    (original / "raw-pre-capture.json").write_text(json.dumps(pre))
    recovery_dir = tmp_path / "recovery"
    recovery_dir.mkdir()
    r = recovery()
    r.freeze_original(original, recovery_dir / "original-evidence.sha256")
    r.freeze_raw(raw, recovery_dir / "raw-before.sha256")
    derived = r.derive(raw, pre, SID)
    counts = {**derived["counts"], "records": derived["records"]}
    comparison = r.compare_operator_counts(derived, counts)
    baseline = r.approve_current_baseline("a" * 64, "operator-approved-current-recovery-baseline")
    files = [{"file": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
              "bytes": p.stat().st_size, "lines": len(p.read_bytes().splitlines()),
              "selected_records": (2 if "depth_2026-10-28" in p.name else
                                   1 if "trade_2026-10-28" in p.name else 0)}
             for p in sorted(raw.iterdir())]
    audit = {"status": "ok", "session_id": SID, "counts": derived["counts"],
             "selected_records": 3, "files": files}
    replay = {"status": "ok", "session_id": SID, "counts": derived["counts"],
              "records": 3, "last_ingest_sequence": 3, "capture_hashes_verified": 3,
              "expected_counts_checked": True, "ready_features": 1,
              "feature_sha256": "b" * 64, "files": files}
    for name, value in (("derived-counts.json", derived), ("operator-counts-compared.json", comparison),
                        ("current-recovery-baseline.json", baseline), ("audit.json", audit),
                        ("replay-1.json", replay), ("replay-2.json", replay)):
        (recovery_dir / name).write_text(json.dumps(value))
    diagnostic = r.verify(derived, audit, [replay, replay],
                          r.parse_raw_manifest(recovery_dir / "raw-before.sha256", raw), raw,
                          comparison, baseline)
    (recovery_dir / "diagnostics.json").write_text(json.dumps(diagnostic))
    return raw, original, recovery_dir


def verify(g, raw, original, recovery_dir, output, **overrides):
    return g.verify_evidence(recovery_dir, original, raw, output,
                             expected_session_id=SID,
                             expected_counts={"book_snapshot": 1, "book_delta": 1, "trade": 1},
                             expected_feature_sha256="b" * 64,
                             expected_ready_features=1,
                             expected_approval_sha256="a" * 64, **overrides)


def test_verify_rejects_wrong_approval_even_with_matching_diagnostic(tmp_path):
    raw, original, rec = evidence(tmp_path)
    baseline_path = rec / "current-recovery-baseline.json"
    baseline = json.loads(baseline_path.read_text())
    baseline["candidate_approval_sha256"] = "c" * 64
    baseline_path.write_text(json.dumps(baseline))
    r = recovery()
    diagnostic = r.verify(
        json.loads((rec / "derived-counts.json").read_text()),
        json.loads((rec / "audit.json").read_text()),
        [json.loads((rec / f"replay-{n}.json").read_text()) for n in (1, 2)],
        r.parse_raw_manifest(rec / "raw-before.sha256", raw), raw,
        json.loads((rec / "operator-counts-compared.json").read_text()), baseline)
    (rec / "diagnostics.json").write_text(json.dumps(diagnostic))
    output = tmp_path / "verified.json"
    with pytest.raises(ValueError, match="approval"):
        verify(gate(), raw, original, rec, output)
    assert not output.exists()


def test_copy_rechecks_approval_and_rejects_changed_baseline(tmp_path):
    raw, original, rec = evidence(tmp_path)
    g = gate()
    verified = tmp_path / "verified.json"
    verify(g, raw, original, rec, verified)
    baseline = rec / "current-recovery-baseline.json"
    value = json.loads(baseline.read_text())
    value["candidate_approval_sha256"] = "c" * 64
    baseline.write_text(json.dumps(value))
    manifest = tmp_path / "completed.json"
    with pytest.raises(ValueError, match="approval"):
        g.copy_verified(verified, raw, tmp_path / "copy", manifest)
    assert not manifest.exists()


def test_verify_rejects_wrong_ready_count_even_with_matching_diagnostic(tmp_path):
    raw, original, rec = evidence(tmp_path)
    for number in (1, 2):
        path = rec / f"replay-{number}.json"
        replay = json.loads(path.read_text())
        replay["ready_features"] = 2
        path.write_text(json.dumps(replay))
    r = recovery()
    derived = json.loads((rec / "derived-counts.json").read_text())
    audit = json.loads((rec / "audit.json").read_text())
    replays = [json.loads((rec / f"replay-{number}.json").read_text()) for number in (1, 2)]
    comparison = json.loads((rec / "operator-counts-compared.json").read_text())
    baseline = json.loads((rec / "current-recovery-baseline.json").read_text())
    frozen = r.parse_raw_manifest(rec / "raw-before.sha256", raw)
    diagnostic = r.verify(derived, audit, replays, frozen, raw, comparison, baseline)
    assert diagnostic["ready_features"] == [2, 2]
    (rec / "diagnostics.json").write_text(json.dumps(diagnostic))
    output = tmp_path / "verified.json"
    with pytest.raises(ValueError, match="ready"):
        verify(gate(), raw, original, rec, output)
    assert not output.exists()


def test_verify_then_copy_extractor_compatible_and_source_unmodified(tmp_path):
    raw, original, rec = evidence(tmp_path)
    before = {p: (p.read_bytes(), p.stat().st_mode) for d in (raw, original, rec)
              for p in d.iterdir() if p.is_file()}
    g = gate()
    verified_path = tmp_path / "verified.json"
    verified = verify(g, raw, original, rec, verified_path)
    assert verified["source_files"] and len(verified["source_files"]) == 4
    copied = tmp_path / "copied"
    manifest_path = tmp_path / "completed.json"
    manifest = g.copy_verified(verified_path, raw, copied, manifest_path)
    assert manifest["manifest_version"] == "completed-raw-copy-v1"
    assert manifest["completed"] is True
    assert manifest["expected_counts"] == {"book_snapshot": 1, "book_delta": 1, "trade": 1}
    assert manifest["expected_feature_sha256"] == "b" * 64
    assert verified["expected_ready_features"] == 1
    assert verified["expected_approval_sha256"] == "a" * 64
    assert len(manifest["files"]) == 4
    assert {p.name for p in copied.iterdir()} == {f["name"] for f in manifest["files"]}
    assert not copied.stat().st_mode & 0o222
    for item in manifest["files"]:
        p = copied / item["name"]
        assert not p.stat().st_mode & 0o222
        assert p.read_bytes() == (raw / p.name).read_bytes()
        assert hashlib.sha256(p.read_bytes()).hexdigest() == item["sha256"]
        assert p.stat().st_size == item["bytes"]
    assert manifest["copy_completion_provenance"] == "copy_bytes_directly_verified"
    assert manifest["source_session_completion_provenance"] == "operator_report_not_direct_host_inspection"
    assert manifest["independent_completion_verified"] is False
    assert manifest["soak_acceptance"] is False
    assert all((p.read_bytes(), p.stat().st_mode) == value for p, value in before.items())
    assert json.loads(manifest_path.read_text()) == manifest
    assert json.loads(verified_path.read_text()) == verified
    with pytest.raises(FileExistsError):
        g.copy_verified(verified_path, raw, copied, tmp_path / "again.json")


@pytest.mark.parametrize("change", ["original", "diagnostic", "counts", "audit", "replay", "raw", "extra", "missing"])
def test_verify_rejects_bad_evidence_without_publication(tmp_path, change):
    raw, original, rec = evidence(tmp_path)
    if change == "original":
        (original / "raw-pre-capture.json").write_bytes(b'changed')
    elif change == "diagnostic":
        p = rec / "diagnostics.json"
        value = json.loads(p.read_text()); value["files_checked"] = 2; p.write_text(json.dumps(value))
    elif change == "counts":
        p = rec / "operator-counts-compared.json"
        value = json.loads(p.read_text()); value["provenance"] = "self_reported_as_verified"; p.write_text(json.dumps(value))
    elif change == "audit":
        p = rec / "audit.json"
        value = json.loads(p.read_text()); value["files"][0]["bytes"] += 1; p.write_text(json.dumps(value))
    elif change == "replay":
        p = rec / "replay-2.json"
        value = json.loads(p.read_text()); value["feature_sha256"] = "c" * 64; p.write_text(json.dumps(value))
    elif change == "raw":
        p = next(raw.glob("*depth*28*")); p.write_bytes(p.read_bytes() + b'X')
    elif change == "extra":
        (raw / "binance_btcusdt_depth_2026-10-30.jsonl").write_bytes(b'')
    else:
        next(raw.glob("*trade*29*")).unlink()
    output = tmp_path / "verified.json"
    with pytest.raises((ValueError, OSError)):
        verify(gate(), raw, original, rec, output)
    assert not output.exists()


def test_verify_rejects_forged_derived_counts_even_when_diagnostic_unchanged(tmp_path):
    raw, original, rec = evidence(tmp_path)
    p = rec / "derived-counts.json"
    derived = json.loads(p.read_text())
    derived["unverified_claim"] = True
    p.write_text(json.dumps(derived))
    with pytest.raises(ValueError, match="Derived recovery counts"):
        verify(gate(), raw, original, rec, tmp_path / "verified.json")
    assert not (tmp_path / "verified.json").exists()


def test_copy_rechecks_source_hash_and_no_manifest_on_failure(tmp_path):
    raw, original, rec = evidence(tmp_path)
    g = gate(); v = tmp_path / "verified.json"
    verify(g, raw, original, rec, v)
    p = next(raw.glob("*depth*28*")); p.write_bytes(p.read_bytes() + b'X')
    manifest = tmp_path / "completed.json"
    with pytest.raises(ValueError):
        g.copy_verified(v, raw, tmp_path / "copied", manifest)
    assert not manifest.exists()


def test_copy_rejects_overlaps_and_symlinks(tmp_path):
    raw, original, rec = evidence(tmp_path)
    g = gate(); v = tmp_path / "verified.json"
    verify(g, raw, original, rec, v)
    for path in (raw / "nested", original / "nested", rec / "nested"):
        with pytest.raises(ValueError):
            g.copy_verified(v, raw, path, tmp_path / "completed.json")
        assert not path.exists()
    link = tmp_path / "linked"
    link.symlink_to(raw, target_is_directory=True)
    with pytest.raises(ValueError):
        g.copy_verified(v, link, tmp_path / "copy", tmp_path / "completed.json")


def test_copy_rejects_tampered_verified_metadata(tmp_path):
    raw, original, rec = evidence(tmp_path)
    g = gate(); v = tmp_path / "verified.json"
    verify(g, raw, original, rec, v)
    data = json.loads(v.read_text()); data["source_files"][0]["sha256"] = "0" * 64
    v.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        g.copy_verified(v, raw, tmp_path / "copied", tmp_path / "completed.json")
    assert not (tmp_path / "completed.json").exists()


def test_copy_failure_keeps_partial_directory_without_valid_manifest(tmp_path, monkeypatch):
    raw, original, rec = evidence(tmp_path)
    g = gate(); verified = tmp_path / "verified.json"
    verify(g, raw, original, rec, verified)
    real_read = g._read_source
    def fail_on_second_copy(path, cap, deadline, destination=None):
        if destination is not None and "_2026-10-29" in str(path):
            raise OSError("synthetic copy failure")
        return real_read(path, cap, deadline, destination)
    monkeypatch.setattr(g, "_read_source", fail_on_second_copy)
    copy_dir = tmp_path / "partial"; manifest = tmp_path / "manifest.json"
    with pytest.raises(OSError, match="synthetic copy failure"):
        g.copy_verified(verified, raw, copy_dir, manifest)
    assert copy_dir.exists()
    assert not manifest.exists()
    assert (raw / "binance_btcusdt_depth_2026-10-29.jsonl").exists()


def test_manifest_directory_fsync_failure_does_not_publish_success(tmp_path, monkeypatch):
    raw, original, rec = evidence(tmp_path)
    g = gate(); verified = tmp_path / "verified.json"
    verify(g, raw, original, rec, verified)
    original_fsync = g.os.fsync
    calls = 0
    def fail_directory_fsync(fd):
        nonlocal calls
        calls += 1
        if calls == 6:
            raise OSError("synthetic directory fsync failure")
        return original_fsync(fd)
    monkeypatch.setattr(g.os, "fsync", fail_directory_fsync)
    manifest = tmp_path / "manifest.json"
    with pytest.raises(OSError, match="synthetic directory fsync failure"):
        g.copy_verified(verified, raw, tmp_path / "copied", manifest)
    assert not manifest.exists()


def test_copy_signal_immediately_after_manifest_link_leaves_no_completion(tmp_path, monkeypatch):
    raw, original, rec = evidence(tmp_path)
    g = gate()
    verified = tmp_path / "verified.json"
    verify(g, raw, original, rec, verified)
    before = {p: (p.read_bytes(), p.stat().st_mode) for p in raw.iterdir()}
    real_link = g.os.link
    def signal_after_link(source, destination, **kwargs):
        real_link(source, destination, **kwargs)
        signal.raise_signal(signal.SIGALRM)
    monkeypatch.setattr(g.os, "link", signal_after_link)
    manifest = tmp_path / "completed.json"
    with pytest.raises(ValueError, match="runtime budget"):
        g.copy_verified(verified, raw, tmp_path / "copied", manifest)
    assert not manifest.exists()
    assert all((p.read_bytes(), p.stat().st_mode) == saved for p, saved in before.items())


def test_publish_failure_after_link_preserves_unrelated_replacement(tmp_path, monkeypatch):
    g = gate()
    real_fsync = g.os.fsync
    def replace_during_directory_fsync(fd):
        if os.fstat(fd).st_mode & 0o170000 == 0o040000:
            os.unlink(output)
            output.write_bytes(b"unrelated owner")
            raise OSError("synthetic post-link failure")
        return real_fsync(fd)
    monkeypatch.setattr(g.os, "fsync", replace_during_directory_fsync)
    output = tmp_path / "output.json"
    with pytest.raises(OSError, match="post-link"):
        g._publish(output, {"completed": True})
    assert output.read_bytes() == b"unrelated owner"


def test_verify_rejects_oversized_source_before_read(tmp_path):
    raw, original, rec = evidence(tmp_path)
    first = next(raw.glob("*depth*28*"))
    with first.open("r+b") as out:
        out.truncate(768 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="byte budget"):
        verify(gate(), raw, original, rec, tmp_path / "verified.json")
    assert not (tmp_path / "verified.json").exists()


def test_aggregate_excess_sparse_files_rejected_before_any_source_read(tmp_path, monkeypatch):
    raw, original, rec = evidence(tmp_path)
    sources = sorted(raw.iterdir())
    for path in sources[:2]:
        with path.open("r+b") as out:
            out.truncate(400 * 1024 * 1024)
    g = gate()
    reads = []
    real_read = g._read_source
    def track_read(path, *args, **kwargs):
        reads.append(path)
        return real_read(path, *args, **kwargs)
    monkeypatch.setattr(g, "_read_source", track_read)
    output = tmp_path / "verified.json"
    with pytest.raises(ValueError, match="byte budget"):
        verify(g, raw, original, rec, output)
    assert reads == []
    assert not output.exists()


def test_verify_rejects_symlinked_raw_entry(tmp_path):
    raw, original, rec = evidence(tmp_path)
    p = next(raw.glob("*depth*29*"))
    p.unlink(); p.symlink_to(raw / "binance_btcusdt_depth_2026-10-28.jsonl")
    with pytest.raises((ValueError, OSError)):
        verify(gate(), raw, original, rec, tmp_path / "verified.json")
    assert not (tmp_path / "verified.json").exists()


def test_verify_rejects_expired_runtime_budget(tmp_path):
    raw, original, rec = evidence(tmp_path)
    with pytest.raises(ValueError, match="runtime budget"):
        verify(gate(), raw, original, rec, tmp_path / "verified.json",
               max_runtime_seconds=0.000001)
    assert not (tmp_path / "verified.json").exists()


def test_verify_interrupts_slow_original_verification(tmp_path, monkeypatch):
    import time
    raw, original, rec = evidence(tmp_path)
    g = gate()
    monkeypatch.setattr(g, "verify_original_evidence", lambda *args: time.sleep(0.2))
    start = time.monotonic()
    with pytest.raises(ValueError, match="runtime budget"):
        verify(g, raw, original, rec, tmp_path / "verified.json",
               max_runtime_seconds=0.02)
    assert time.monotonic() - start < 0.15
    assert not (tmp_path / "verified.json").exists()


def test_cli_pins_production_counts_not_synthetic_fixture(tmp_path):
    raw, original, rec = evidence(tmp_path)
    out = tmp_path / "verified.json"
    command = [sys.executable, str(HELPER), "verify", "--recovery", str(rec),
               "--original", str(original), "--raw-dir", str(raw), "--output", str(out),
               "--expected-approval-sha256", "a" * 64]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode != 0, result.stdout
    assert "Pinned collector counts mismatch" in result.stderr
    assert not out.exists()


def test_cli_requires_current_approval_digest(tmp_path):
    raw, original, rec = evidence(tmp_path)
    out = tmp_path / "verified.json"
    result = subprocess.run([sys.executable, str(HELPER), "verify", "--recovery", str(rec),
                             "--original", str(original), "--raw-dir", str(raw), "--output", str(out)],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert "--expected-approval-sha256" in result.stderr
    assert not out.exists()
