"""Synthetic-only offline extraction contract tests."""
import hashlib
import json
from pathlib import Path

import pytest

from signal_desk.research.baselines import run_research
from signal_desk.research.extract_prefix import extract_prefix, ExtractError
from signal_desk.research import extract_prefix as extractor
from signal_desk.features.causal import canonical_bytes
from tests.research.test_baselines_s1 import fixture, SPEC, SID


def extract_fixture(raw, *args, **kwargs):
    for path in raw.glob("*.jsonl"):
        path.chmod(0o400)
    raw.chmod(0o500)
    return extract_prefix(raw, *args, **kwargs)


def source_manifest(manifest):
    return {"manifest_version": "completed-raw-copy-v1", "session_id": SID,
            "completed": True, "expected_counts": manifest["expected_counts"],
            "files": manifest["files"]}


def test_extract_preserves_raw_prefix_and_runs_baselines(tmp_path):
    raw, original, spec, rows = fixture(tmp_path)
    original_bytes = {p.name: p.read_bytes() for p in raw.glob("*.jsonl")}
    output = tmp_path / "prefix"
    result = extract_fixture(raw, source_manifest(original), SPEC, output,
                            synthetic_session_id=SID, max_records=7)
    assert result["status"] == "complete_prefix"
    assert result["selected_records"] == 7
    assert result["last_ingest_sequence"] == 7
    assert result["truncation_scope"] == "record_limit"
    assert result["usable_duration_status"] == "insufficient_for_proposed_60_day_split"
    extracted = [json.loads(line) for p in output.glob("*.jsonl") for line in p.read_bytes().splitlines()]
    assert sorted(extracted, key=lambda r: r["data_quality"]["ingest_sequence"]) == rows[:7]
    for name, data in original_bytes.items():
        assert (raw / name).read_bytes() == data
        expected = b"".join(line + b"\n" for line in data.splitlines()
                            if json.loads(line)["data_quality"]["ingest_sequence"] <= 7)
        if expected:
            assert (output / name).read_bytes() == expected
    input_manifest = json.loads((output / "research-input-v1.json").read_text())
    assert input_manifest["spec_sha256"] == hashlib.sha256(SPEC.read_bytes()).hexdigest()
    assert sum(input_manifest["expected_counts"].values()) == 7
    assert run_research(output, input_manifest, spec)
    assert output.joinpath("extraction-v1.json").exists()
    with pytest.raises(FileExistsError):
        extract_fixture(raw, source_manifest(original), SPEC, output, synthetic_session_id=SID)


def test_exact_byte_boundary_stops_before_next_record(tmp_path):
    raw, original, _, rows = fixture(tmp_path)
    boundary = sum(len(canonical_bytes(row)) + 1 for row in rows[:3])
    first = extract_fixture(raw, source_manifest(original), SPEC, tmp_path / "exact",
                           synthetic_session_id=SID, max_output_bytes=boundary)
    second = extract_fixture(raw, source_manifest(original), SPEC, tmp_path / "short",
                            synthetic_session_id=SID, max_output_bytes=boundary - 1)
    assert (first["selected_records"], first["serialized_raw_bytes"], first["truncation_scope"]) == (3, boundary, "byte_limit")
    assert second["selected_records"] == 2
    assert first["source_capture_hashes_verified"] == sum(original["expected_counts"].values())


def test_repeated_extraction_is_byte_deterministic(tmp_path):
    raw, original, _, _ = fixture(tmp_path)
    for dirname in ("one", "two"):
        extract_fixture(raw, source_manifest(original), SPEC, tmp_path / dirname,
                       synthetic_session_id=SID, max_records=8)
    assert {p.name: p.read_bytes() for p in (tmp_path / "one").iterdir()} == {
        p.name: p.read_bytes() for p in (tmp_path / "two").iterdir()}


def test_pinned_production_identity_and_counts_reject_fixture(tmp_path):
    raw, original, _, _ = fixture(tmp_path)
    with pytest.raises(ExtractError, match="pinned session"):
        extract_fixture(raw, source_manifest(original), SPEC, tmp_path / "rejected")
    assert not (tmp_path / "rejected").exists()


def test_corruption_after_prefix_fails_without_usable_manifest(tmp_path):
    raw, original, _, _ = fixture(tmp_path)
    path = next(raw.glob("*trade*.jsonl"))
    lines = path.read_bytes().splitlines(keepends=True)
    event = json.loads(lines[-1])
    event["data_quality"]["feature_sha256"] = "0" * 64
    lines[-1] = canonical_bytes(event) + b"\n"
    path.write_bytes(b"".join(lines))
    manifest = source_manifest(original)
    manifest["files"] = [{"name": p.name, "bytes": p.stat().st_size,
                          "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                         for p in sorted(raw.glob("*.jsonl"))]
    output = tmp_path / "bad"
    with pytest.raises(ExtractError, match="feature hash"):
        extract_fixture(raw, manifest, SPEC, output, synthetic_session_id=SID, max_records=3)
    assert output.exists() and not (output / "research-input-v1.json").exists()


def test_source_hash_mismatch_fails_without_usable_manifest(tmp_path):
    raw, original, _, _ = fixture(tmp_path)
    manifest = source_manifest(original)
    manifest["files"][0]["sha256"] = "0" * 64
    output = tmp_path / "bad-hash"
    with pytest.raises(ExtractError, match="SHA-256"):
        extract_fixture(raw, manifest, SPEC, output, synthetic_session_id=SID, max_records=3)
    assert not (output / "research-input-v1.json").exists()


def test_ordered_feature_output_digest_mismatch_fails_without_manifest(tmp_path):
    raw, original, _, _ = fixture(tmp_path)
    manifest = source_manifest(original)
    manifest["expected_feature_sha256"] = "0" * 64
    output = tmp_path / "bad-feature-output-digest"
    with pytest.raises(ExtractError, match="ordered feature digest"):
        extract_fixture(raw, manifest, SPEC, output, synthetic_session_id=SID)
    assert not (output / "research-input-v1.json").exists()


def test_fsync_failure_keeps_output_incomplete(tmp_path, monkeypatch):
    raw, original, _, _ = fixture(tmp_path)
    monkeypatch.setattr(extractor.os, "fsync", lambda fd: (_ for _ in ()).throw(OSError("disk failure")))
    output = tmp_path / "fsync-failed"
    with pytest.raises(OSError, match="disk failure"):
        extract_fixture(raw, source_manifest(original), SPEC, output, synthetic_session_id=SID)
    assert not (output / "research-input-v1.json").exists()


def test_prefix_without_depth_bridge_is_not_published(tmp_path):
    raw, original, _, _ = fixture(tmp_path)
    output = tmp_path / "unbridged"
    with pytest.raises(ExtractError, match="bridge"):
        extract_fixture(raw, source_manifest(original), SPEC, output,
                       synthetic_session_id=SID, max_records=1)
    assert not (output / "research-input-v1.json").exists()


def test_original_noncanonical_jsonl_bytes_are_retained(tmp_path):
    raw, original, _, _ = fixture(tmp_path)
    path = next(raw.glob("*depth*.jsonl"))
    lines = path.read_bytes().splitlines(keepends=True)
    lines[0] = b"  " + lines[0][:-1] + b" \n"
    path.write_bytes(b"".join(lines))
    manifest = source_manifest(original)
    manifest["files"] = [{"name": p.name, "bytes": p.stat().st_size,
                          "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                         for p in sorted(raw.glob("*.jsonl"))]
    output = tmp_path / "original-bytes"
    extract_fixture(raw, manifest, SPEC, output, synthetic_session_id=SID, max_records=3)
    assert (output / path.name).read_bytes().startswith(lines[0])


def test_writable_copy_fails_before_creating_output(tmp_path):
    raw, original, _, _ = fixture(tmp_path)
    output = tmp_path / "writable-output"
    with pytest.raises(ExtractError, match="read-only"):
        extract_prefix(raw, source_manifest(original), SPEC, output, synthetic_session_id=SID)
    assert not output.exists()


def test_deadline_expiry_during_manifest_publication_leaves_no_runner_manifest(tmp_path, monkeypatch):
    raw, original, _, _ = fixture(tmp_path)
    clock = [0.0]
    monkeypatch.setattr(extractor.time, "monotonic", lambda: clock[0])
    real_link = extractor.os.link
    def delayed_link(source, destination):
        real_link(source, destination)
        clock[0] = 901.0
    monkeypatch.setattr(extractor.os, "link", delayed_link)
    output = tmp_path / "expired"
    with pytest.raises(ExtractError, match="runtime"):
        extract_fixture(raw, source_manifest(original), SPEC, output, synthetic_session_id=SID)
    assert not (output / "research-input-v1.json").exists()


def test_output_ancestor_of_source_and_symlinked_parent_rejected(tmp_path):
    raw, original, _, _ = fixture(tmp_path)
    with pytest.raises(ExtractError, match="outside"):
        extract_fixture(raw, source_manifest(original), SPEC, tmp_path,
                        synthetic_session_id=SID)
    alias = tmp_path / "source-alias"
    alias.symlink_to(raw, target_is_directory=True)
    with pytest.raises(ExtractError, match="outside"):
        extract_fixture(raw, source_manifest(original), SPEC, alias / "nested",
                        synthetic_session_id=SID)


@pytest.mark.parametrize("declared_total", [547115599, 768 * 1024 * 1024])
def test_larger_bounded_source_reaches_reader_without_publishing(tmp_path, monkeypatch, declared_total):
    raw, original, _, _ = fixture(tmp_path)
    files = sorted(raw.glob("*.jsonl"))
    size = declared_total - files[1].stat().st_size
    with files[0].open("r+b") as stream:
        stream.truncate(size)  # Sparse metadata fixture; do not scan its padding.
    manifest = source_manifest(original)
    for item in manifest["files"]:
        if item["name"] == files[0].name:
            item["bytes"] = size
    class ReachedReader(Exception):
        pass
    def reader(*args, **kwargs):
        raise ReachedReader
    monkeypatch.setattr(extractor, "SessionInput", reader)
    output = tmp_path / "not-published"
    with pytest.raises(ReachedReader):
        extract_fixture(raw, manifest, SPEC, output, synthetic_session_id=SID)
    assert not output.exists()


def test_above_source_ceiling_rejected_before_reader_or_publication(tmp_path, monkeypatch):
    raw, original, _, _ = fixture(tmp_path)
    files = sorted(raw.glob("*.jsonl"))
    size = 768 * 1024 * 1024 + 1 - files[1].stat().st_size
    with files[0].open("r+b") as stream:
        stream.truncate(size)
    manifest = source_manifest(original)
    for item in manifest["files"]:
        if item["name"] == files[0].name:
            item["bytes"] = size
    def forbidden_reader(*args, **kwargs):
        pytest.fail("Source was scanned before enforcing declared byte ceiling")
    monkeypatch.setattr(extractor, "SessionInput", forbidden_reader)
    output = tmp_path / "not-published"
    with pytest.raises(ExtractError, match="Source byte budget exhausted"):
        extract_fixture(raw, manifest, SPEC, output, synthetic_session_id=SID)
    assert not output.exists()
