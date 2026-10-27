from pathlib import Path

from signal_desk.storage.jsonl import append_jsonl
from signal_desk.storage.manifest import build_manifest
from signal_desk.schemas.validate import validate_json


def test_storage_manifest_hashes_files(tmp_path: Path):
    append_jsonl(tmp_path / "raw" / "events.jsonl", {"x": 1})
    manifest = build_manifest(tmp_path, profile="100gb_2gb")
    validate_json(manifest, "storage_manifest.schema.json")
    assert manifest["files"][0]["kind"] == "raw"
    assert manifest["files"][0]["bytes"] > 0
