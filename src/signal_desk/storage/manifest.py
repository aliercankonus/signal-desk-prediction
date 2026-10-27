from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from signal_desk.config.loader import validate_config
from signal_desk.schemas.validate import validate_json


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def classify(path: Path) -> str:
    parts = set(path.parts)
    if "raw" in parts:
        return "raw"
    if "features" in parts:
        return "feature"
    if "ledger" in parts:
        return "ledger"
    if "reports" in parts:
        return "report"
    if "models" in parts:
        return "model"
    if "status" in parts:
        return "status"
    return "other"


def build_manifest(base_path: str | Path, *, profile: str, notes: str = "") -> dict:
    base = Path(base_path)
    files = []
    if base.exists():
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            if path.name.endswith(".tmp"):
                continue
            rel = path.relative_to(base).as_posix()
            files.append({
                "path": rel,
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
                "kind": classify(path),
                "retention_pin": False,
            })
    payload = {
        "manifest_id": "stor_" + hashlib.sha256((str(base) + utc_now_iso()).encode()).hexdigest()[:20],
        "created_ts": utc_now_iso(),
        "profile": profile,
        "files": files,
        "notes": notes,
    }
    validate_json(payload, "storage_manifest.schema.json")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/config.yaml")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    config = validate_config(args.config)
    manifest = build_manifest(config["storage"]["base_path"], profile=config["resources"]["profile"], notes="generated_by_v15")
    text = json.dumps(manifest, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
