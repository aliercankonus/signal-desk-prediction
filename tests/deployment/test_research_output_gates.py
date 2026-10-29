"""Synthetic output-gate fixtures; no real source or Docker access."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "scripts/review/research_output_gates.py"
SPEC = ROOT / "docs/research/s1_experiment_v1.json"
SID = "cb8a0767d7284b8aaa3d09fbca7095f2"
COUNTS = {"book_snapshot": 1, "book_delta": 35936, "trade": 222238}
DIGEST = "bafabf00f920c948a7f952425d105197039af0104c0b28b65904afdbe94bf6c0"
SYNTHETIC_COUNTS = {"book_snapshot": 1, "book_delta": 0, "trade": 0}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def fixture(tmp_path):
    output = tmp_path / "output"
    prefix = output / "prefix"
    prefix.mkdir(parents=True)
    raw = (b'{"event_type":"book_snapshot","data_quality":{"collector_session_id":"'
           + SID.encode() + b'","ingest_sequence":1,"applied_ts":"2026-10-29T00:00:00+00:00"}}\n')
    copy = tmp_path / "raw-copy"
    copy.mkdir()
    (copy / "btc_depth_1.jsonl").write_bytes(raw)
    (prefix / "btc_depth_1.jsonl").write_bytes(raw)
    files = [{"name": "btc_depth_1.jsonl", "bytes": len(raw),
              "sha256": hashlib.sha256(raw).hexdigest()}]
    source = {"manifest_version": "completed-raw-copy-v1", "completed": True,
              "session_id": SID, "expected_counts": COUNTS.copy(),
              "expected_feature_sha256": DIGEST, "files": files + [
                  {"name": f"btc_trade_{n}.jsonl", "bytes": 0,
                   "sha256": hashlib.sha256(b"").hexdigest()} for n in range(3)]}
    source_path = tmp_path / "completed.json"
    for item in source["files"][1:]:
        (copy / item["name"]).write_bytes(b"")
    for path in copy.iterdir():
        path.chmod(0o400)
    copy.chmod(0o500)
    source_path.write_bytes(canonical(source) + b"\n")
    extract = {"manifest_version": "research-extraction-v1", "status": "complete_prefix",
               "source_session_id": SID, "source_manifest_sha256": hashlib.sha256(canonical(source)).hexdigest(),
               "source_files": sorted(source["files"], key=lambda f: f["name"]), "source_expected_counts": COUNTS.copy(),
               "source_verified_counts": COUNTS.copy(), "source_capture_hashes_verified": sum(COUNTS.values()),
               "source_verified_feature_sha256": DIGEST,
               "selection_policy": {"start_ingest_sequence": 1, "max_records": 90000,
                                    "max_serialized_raw_bytes": 128 * 1024 * 1024,
                                    "stop_before_exceeding_either_limit": True},
               "selected_records": 1,
               "selected_counts": {"book_snapshot": 1, "book_delta": 0, "trade": 0},
               "first_ingest_sequence": 1, "last_ingest_sequence": 1,
               "first_applied_ts": "2026-10-29T00:00:00+00:00",
               "last_applied_ts": "2026-10-29T00:00:00+00:00",
               "usable_duration_seconds": 0.0,
               "usable_duration_status": "insufficient_for_proposed_60_day_split",
               "truncation_scope": "source_end",
               "scope": "verified stored source and raw prefix; not full-session research, exchange completeness, model selection or PnL",
               "serialized_raw_bytes": len(raw), "output_files": [f.copy() for f in files]}
    runner = {"manifest_version": "research-input-v1", "session_id": SID,
              "spec_sha256": hashlib.sha256(SPEC.read_bytes()).hexdigest(),
              "expected_counts": extract["selected_counts"].copy(), "files": [f.copy() for f in files]}
    for name, value in (("extraction-v1.json", extract), ("research-input-v1.json", runner)):
        (prefix / name).write_bytes(canonical(value) + b"\n")
    return output, source_path, extract, runner


def run(output, source, spec=SPEC, expected_source_counts=SYNTHETIC_COUNTS):
    module_spec = importlib.util.spec_from_file_location("synthetic_output_gate", GATE)
    assert module_spec is not None and module_spec.loader is not None
    gate = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(gate)
    try:
        gate.validate(output, source, spec, source.parent / "raw-copy",
                      expected_source_counts=expected_source_counts)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return SimpleNamespace(returncode=2, stderr=str(exc))
    return SimpleNamespace(returncode=0, stderr="")


def put(path, value):
    path.write_bytes(canonical(value) + b"\n")


def update_source(tmp_path, extract):
    source_path = tmp_path / "completed.json"
    source = json.loads(source_path.read_text())
    for item in source["files"]:
        raw = (tmp_path / "raw-copy" / item["name"]).read_bytes()
        item.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    put(source_path, source)
    extract["source_files"] = sorted(source["files"], key=lambda f: f["name"])
    extract["source_manifest_sha256"] = hashlib.sha256(canonical(source)).hexdigest()
    return source_path


def test_requires_raw_copy_dir_cli(tmp_path):
    output, source, _, _ = fixture(tmp_path)
    result = subprocess.run([sys.executable, str(GATE), "validate", "--output", str(output),
                             "--source-manifest", str(source), "--spec", str(SPEC)],
                            capture_output=True, text=True)
    assert result.returncode != 0 and "--raw-copy-dir" in result.stderr


def test_rejects_self_consistent_forged_output_bytes(tmp_path):
    output, source, extract, runner = fixture(tmp_path)
    raw = output / "prefix" / "btc_depth_1.jsonl"
    forged = raw.read_bytes().replace(b'"book_snapshot"', b'"book_snapshot","forged":true')
    raw.write_bytes(forged)
    item = {"name": raw.name, "bytes": len(forged), "sha256": hashlib.sha256(forged).hexdigest()}
    extract["output_files"] = runner["files"] = [item]
    extract["serialized_raw_bytes"] = len(forged)
    put(output / "prefix" / "extraction-v1.json", extract)
    put(output / "prefix" / "research-input-v1.json", runner)
    assert run(output, source).returncode != 0


def test_rejects_false_record_limit_for_one_record(tmp_path):
    output, source, extract, _ = fixture(tmp_path)
    extract["truncation_scope"] = "record_limit"
    put(output / "prefix" / "extraction-v1.json", extract)
    assert run(output, source).returncode != 0


def test_rejects_corrupt_copy_even_if_manifest_claims_original(tmp_path):
    output, source, _, _ = fixture(tmp_path)
    copy = tmp_path / "raw-copy" / "btc_depth_1.jsonl"
    copy.chmod(0o600)
    copy.write_bytes(copy.read_bytes() + b"\n")
    copy.chmod(0o400)
    assert run(output, source).returncode != 0


def test_accepts_other_session_lines_in_source_copy(tmp_path):
    output, _, extract, _ = fixture(tmp_path)
    copy = tmp_path / "raw-copy" / "btc_depth_1.jsonl"
    other = b'{"event_type":"trade","data_quality":{"collector_session_id":"other","ingest_sequence":1}}\n'
    copy.chmod(0o600)
    copy.write_bytes(other + copy.read_bytes() + other)
    copy.chmod(0o400)
    source = update_source(tmp_path, extract)
    put(output / "prefix" / "extraction-v1.json", extract)
    assert run(output, source).returncode == 0


def test_rejects_source_end_when_next_session_record_exists(tmp_path):
    output, _, extract, _ = fixture(tmp_path)
    copy = tmp_path / "raw-copy" / "btc_trade_0.jsonl"
    copy.chmod(0o600)
    copy.write_bytes(b'{"event_type":"trade","data_quality":{"collector_session_id":"'
                     + SID.encode() + b'","ingest_sequence":2}}\n')
    copy.chmod(0o400)
    source = update_source(tmp_path, extract)
    put(output / "prefix" / "extraction-v1.json", extract)
    assert run(output, source).returncode != 0


def test_accepts_exact_two_stream_sequence_prefix(tmp_path):
    output, _, extract, runner = fixture(tmp_path)
    trade = (b'{"event_type":"trade","data_quality":{"collector_session_id":"'
             + SID.encode() + b'","ingest_sequence":2,"applied_ts":"2026-10-29T00:00:01+00:00"}}\n')
    copy = tmp_path / "raw-copy" / "btc_trade_0.jsonl"
    copy.chmod(0o600)
    copy.write_bytes(trade)
    copy.chmod(0o400)
    source = update_source(tmp_path, extract)
    (output / "prefix" / copy.name).write_bytes(trade)
    item = {"name": copy.name, "bytes": len(trade), "sha256": hashlib.sha256(trade).hexdigest()}
    extract["output_files"].append(item)
    extract["serialized_raw_bytes"] += len(trade)
    extract["selected_records"] = extract["last_ingest_sequence"] = 2
    extract["last_applied_ts"] = "2026-10-29T00:00:01+00:00"
    extract["usable_duration_seconds"] = 1.0
    extract["selected_counts"]["trade"] = runner["expected_counts"]["trade"] = 1
    runner["files"].append(item)
    put(output / "prefix" / "extraction-v1.json", extract)
    put(output / "prefix" / "research-input-v1.json", runner)
    assert run(output, source, expected_source_counts={"book_snapshot": 1,
               "book_delta": 0, "trade": 1}).returncode == 0


def test_byte_limit_only_when_next_raw_record_exceeds_remaining_budget(tmp_path, monkeypatch):
    output, _, extract, _ = fixture(tmp_path)
    copy = tmp_path / "raw-copy" / "btc_trade_0.jsonl"
    next_raw = (b'{"event_type":"trade","data_quality":{"collector_session_id":"'
                + SID.encode() + b'","ingest_sequence":2}}\n')
    copy.chmod(0o600)
    copy.write_bytes(next_raw)
    copy.chmod(0o400)
    source = update_source(tmp_path, extract)
    extract["truncation_scope"] = "byte_limit"
    spec = importlib.util.spec_from_file_location("output_gate", GATE)
    assert spec is not None and spec.loader is not None
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    raw_size = extract["serialized_raw_bytes"]
    monkeypatch.setattr(gate, "MAX_BYTES", raw_size + len(next_raw) - 1)
    extract["selection_policy"]["max_serialized_raw_bytes"] = gate.MAX_BYTES
    put(output / "prefix" / "extraction-v1.json", extract)
    assert gate.validate(output, source, SPEC, tmp_path / "raw-copy",
                         expected_source_counts={"book_snapshot": 1, "book_delta": 0, "trade": 1}) is True
    monkeypatch.setattr(gate, "MAX_BYTES", raw_size + len(next_raw))
    extract["selection_policy"]["max_serialized_raw_bytes"] = gate.MAX_BYTES
    put(output / "prefix" / "extraction-v1.json", extract)
    with pytest.raises(ValueError, match="byte limit"):
        gate.validate(output, source, SPEC, tmp_path / "raw-copy",
                      expected_source_counts={"book_snapshot": 1, "book_delta": 0, "trade": 1})


def test_rejects_copy_changed_after_hash_before_prefix_compare(tmp_path, monkeypatch):
    output, source, _, _ = fixture(tmp_path)
    spec = importlib.util.spec_from_file_location("output_gate_race", GATE)
    assert spec is not None and spec.loader is not None
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    original = gate._verify_copy
    def mutate_after_hash(directory, entries):
        result = original(directory, entries)
        raw = tmp_path / "raw-copy" / "btc_depth_1.jsonl"
        raw.chmod(0o600)
        raw.write_bytes(raw.read_bytes().replace(b'"book_snapshot"', b'"book_snapshot","tampered":1'))
        raw.chmod(0o400)
        return result
    monkeypatch.setattr(gate, "_verify_copy", mutate_after_hash)
    with pytest.raises(ValueError, match="COPY changed"):
        gate.validate(output, source, SPEC, tmp_path / "raw-copy",
                      expected_source_counts=SYNTHETIC_COUNTS)


def test_valid_synthetic_prefix(tmp_path):
    output, source, _, _ = fixture(tmp_path)
    result = run(output, source)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("mutation", ["status", "session", "source_hash", "source_counts",
                                      "selected_counts", "selected_records", "runner_spec",
                                      "oversize_policy", "bad_digest", "extra_file", "huge_metadata"])
def test_rejects_malformed_or_mismatched_output(tmp_path, mutation):
    output, source, extract, runner = fixture(tmp_path)
    prefix = output / "prefix"
    if mutation == "status":
        extract["status"] = "incomplete"
    elif mutation == "session":
        extract["source_session_id"] = "0" * 32
    elif mutation == "source_hash":
        extract["source_manifest_sha256"] = "0" * 64
    elif mutation == "source_counts":
        extract["source_verified_counts"]["trade"] = 9
    elif mutation == "selected_counts":
        extract["selected_counts"]["trade"] = 2
    elif mutation == "selected_records":
        extract["selected_records"] = 90001
    elif mutation == "runner_spec":
        runner["spec_sha256"] = "0" * 64
    elif mutation == "oversize_policy":
        extract["selection_policy"]["max_serialized_raw_bytes"] = 128 * 1024 * 1024 + 1
    elif mutation == "bad_digest":
        runner["files"][0]["sha256"] = "0" * 64
    elif mutation == "extra_file":
        (prefix / "extra.bin").write_bytes(b"evil")
    elif mutation == "huge_metadata":
        (prefix / "extraction-v1.json").write_bytes(b" " * (65537))
    if mutation != "huge_metadata":
        put(prefix / "extraction-v1.json", extract)
        put(prefix / "research-input-v1.json", runner)
    assert run(output, source).returncode != 0


def test_accepts_known_incomplete_temp_files_only(tmp_path):
    output, source, _, _ = fixture(tmp_path)
    (output / "prefix" / ".extraction-v1.json.incomplete").write_bytes(b"pending")
    (output / "prefix" / ".research-input-v1.json.incomplete").write_bytes(b"pending")
    assert run(output, source).returncode == 0


def test_rejects_symlinked_output_file(tmp_path):
    output, source, _, _ = fixture(tmp_path)
    raw = output / "prefix" / "btc_depth_1.jsonl"
    content = raw.read_bytes()
    raw.unlink()
    target = tmp_path / "target"
    target.write_bytes(content)
    raw.symlink_to(target)
    assert run(output, source).returncode != 0


def test_larger_completed_source_does_not_consume_prefix_output_budget(tmp_path):
    output, source_path, extract, _ = fixture(tmp_path)
    source = json.loads(source_path.read_text())
    source["files"][0]["bytes"] = 130 * 1024 * 1024
    put(source_path, source)
    extract["source_files"] = source["files"]
    extract["source_manifest_sha256"] = hashlib.sha256(canonical(source)).hexdigest()
    put(output / "prefix" / "extraction-v1.json", extract)
    assert run(output, source_path).returncode != 0  # Exact copy bytes must agree with manifest.


def test_rejects_completed_source_without_four_recognized_files(tmp_path):
    output, source_path, extract, _ = fixture(tmp_path)
    source = json.loads(source_path.read_text())
    source['files'] = source['files'][:1]
    put(source_path, source)
    extract['source_files'] = source['files']
    extract['source_manifest_sha256'] = hashlib.sha256(canonical(source)).hexdigest()
    put(output / 'prefix' / 'extraction-v1.json', extract)
    assert run(output, source_path).returncode != 0


@pytest.mark.parametrize('mutation', ['missing_timestamp', 'wrong_duration', 'wrong_status',
                                      'invalid_truncation', 'invalid_sequence'])
def test_rejects_inconsistent_prefix_semantics(tmp_path, mutation):
    output, source, extract, runner = fixture(tmp_path)
    raw = output / 'prefix' / 'btc_depth_1.jsonl'
    if mutation == 'missing_timestamp':
        del extract['first_applied_ts']
    elif mutation == 'wrong_duration':
        extract['usable_duration_seconds'] = -1
    elif mutation == 'wrong_status':
        extract['usable_duration_status'] = 'duration_only_not_split_approved'
    elif mutation == 'invalid_truncation':
        extract['truncation_scope'] = 'full_soak'
    else:
        content = b'{"event_type":"book_snapshot","data_quality":{"ingest_sequence":2}}\n'
        raw.write_bytes(content)
        changed = {'name': raw.name, 'bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()}
        extract['serialized_raw_bytes'] = len(content)
        extract['output_files'] = [changed]
        runner['files'] = [changed]
    put(output / 'prefix' / 'extraction-v1.json', extract)
    put(output / 'prefix' / 'research-input-v1.json', runner)
    assert run(output, source).returncode != 0


def test_rejects_self_consistent_forged_duration_from_wrong_day(tmp_path):
    output, source, extract, _ = fixture(tmp_path)
    extract['first_applied_ts'] = '2026-10-28T00:00:00+00:00'
    extract['last_applied_ts'] = '2026-10-28T00:00:00+00:00'
    put(output / 'prefix' / 'extraction-v1.json', extract)
    assert run(output, source).returncode != 0


def test_rejects_copy_with_false_full_source_count(tmp_path):
    output, source, _, _ = fixture(tmp_path)
    spec = importlib.util.spec_from_file_location('source_count_gate', GATE)
    assert spec is not None and spec.loader is not None
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    with pytest.raises(ValueError, match='source-session count'):
        gate.validate(output, source, SPEC, tmp_path / 'raw-copy')


def test_cli_keeps_production_count_pin_for_synthetic_one_record_copy(tmp_path):
    output, source, _, _ = fixture(tmp_path)
    result = subprocess.run([sys.executable, str(GATE), 'validate',
        '--output', str(output), '--source-manifest', str(source),
        '--raw-copy-dir', str(tmp_path / 'raw-copy'), '--spec', str(SPEC)],
        capture_output=True, text=True)
    assert result.returncode == 2
    assert 'source-session counts' in result.stderr
