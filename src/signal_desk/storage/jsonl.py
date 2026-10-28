from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def append_jsonl(path: str | Path, obj: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, sort_keys=True, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def iter_jsonl(path: str | Path, *, max_record_bytes: int = 4 * 1024 * 1024):
    """Legacy single-stream iterator; use session replay for cross-file parity."""
    if not 1 <= max_record_bytes <= 4 * 1024 * 1024:
        raise ValueError("Record limit must be within 1..4 MiB")
    with Path(path).open("rb") as source:
        while True:
            raw = source.readline(max_record_bytes + 1)
            if not raw:
                return
            if len(raw) > max_record_bytes or not raw.endswith(b"\n"):
                raise ValueError("Oversized or incomplete JSONL record")
            if raw.strip():
                yield json.loads(raw)
