"""Fail-closed, local acceptance gates; never deploys or changes a host service."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys


def inventory_raw(raw_dir: Path) -> dict:
    """Record size, SHA-256 and identity for every pre-existing raw file."""
    directory = Path(raw_dir)
    if not directory.is_dir():
        raise ValueError("Raw directory missing")
    files = {}
    for path in sorted(directory.iterdir()):
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"Non-regular raw entry: {path.name}")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        after = path.lstat()
        if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns
        ):
            raise ValueError(f"Raw file changed during inventory: {path.name}")
        files[path.name] = {"size": info.st_size, "sha256": digest.hexdigest(),
                            "device": info.st_dev, "inode": info.st_ino}
    return {"files": files}


def verify_raw_prefix(raw_dir: Path, snapshot: dict) -> dict:
    """Require each original inode and byte prefix; appends/new files are allowed."""
    directory = Path(raw_dir)
    if not directory.is_dir() or not isinstance(snapshot, dict) or not isinstance(snapshot.get("files"), dict):
        raise ValueError("Invalid raw inventory")
    originals = snapshot["files"]
    appended = []
    for name, old in sorted(originals.items()):
        if not isinstance(name, str) or name in ("", ".", "..") or Path(name).name != name or "\x00" in name:
            raise ValueError("Invalid inventory filename")
        if not isinstance(old, dict) or type(old.get("size")) is not int or old["size"] < 0 or not isinstance(old.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", old["sha256"]):
            raise ValueError("Invalid inventory record")
        path = directory / name
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except OSError as exc:
            raise ValueError(f"Original raw file missing or replaced: {name}") from exc
        with os.fdopen(fd, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or (before.st_dev, before.st_ino) != (old["device"], old["inode"]):
                raise ValueError(f"Original raw file identity changed: {name}")
            if before.st_size < old["size"]:
                raise ValueError(f"Original raw file shrank: {name}")
            remaining = old["size"]
            digest = hashlib.sha256()
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise ValueError(f"Original raw prefix shortened: {name}")
                digest.update(chunk)
                remaining -= len(chunk)
            after = os.fstat(stream.fileno())
            if (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino) or after.st_size < old["size"] or digest.hexdigest() != old["sha256"]:
                raise ValueError(f"Original raw prefix changed: {name}")
            if after.st_size > old["size"]:
                appended.append(name)
    names = set(originals)
    new = []
    for path in sorted(directory.iterdir()):
        if path.name not in names:
            if not stat.S_ISREG(path.lstat().st_mode):
                raise ValueError(f"Non-regular new raw entry: {path.name}")
            new.append(path.name)
    return {"original_files_checked": len(originals), "appended_files": appended, "new_files": new}


def check_capture(summary: dict, previous_session: str) -> dict:
    """Accept only a fresh, completed 1,000-event bridged capture."""
    sid = summary.get("session_id")
    if not isinstance(sid, str) or not re.fullmatch(r"[0-9a-f]{32}", sid) or sid == previous_session:
        raise ValueError("Capture session is missing or not new")
    if summary.get("status") != "ok" or summary.get("ordering_version") != "session-applied-v1" or summary.get("gap_count") != 0:
        raise ValueError("Capture status, ordering or gap count invalid")
    if summary.get("written_events") != 1000 or summary.get("last_ingest_sequence") != 1000:
        raise ValueError("Capture did not complete exactly 1,000 events")
    depth, trade = summary.get("depth_events"), summary.get("trade_events")
    if type(depth) is not int or type(trade) is not int or depth <= 0 or trade <= 0:
        raise ValueError("Capture requires positive depth and trade counts")
    if depth + trade != 999:
        raise ValueError("Capture counts do not sum to 1,000 with one snapshot")
    return {"session_id": sid, "book_snapshot": 1, "book_delta": depth,
            "trade": trade, "records": 1000}


def check_replays(audit: dict, results: list[dict], capture: dict, manifest: dict[str, str]) -> dict:
    """Require two completed, identical and ready stored-session replays."""
    if len(results) != 2:
        raise ValueError("Exactly two replay results required")
    sid = capture["session_id"]
    expected = {"book_snapshot": capture["book_snapshot"], "book_delta": capture["book_delta"],
                "trade": capture["trade"]}
    if any(type(value) is not int for value in expected.values()) or expected["book_delta"] <= 0 or expected["trade"] <= 0 or sum(expected.values()) != 1000:
        raise ValueError("Invalid positive capture counts")
    if audit.get("status") != "ok" or audit.get("session_id") != sid or audit.get("counts") != expected or audit.get("selected_records") != 1000:
        raise ValueError("Raw audit failed or counts disagree")
    for result in results:
        if result.get("status") != "ok" or result.get("session_id") != sid or result.get("counts") != expected:
            raise ValueError("Replay failed or counts disagree")
        if result.get("records") != 1000 or result.get("expected_counts_checked") is not True or result.get("capture_hashes_verified") != 1000 or result.get("last_ingest_sequence") != 1000:
            raise ValueError("Replay did not verify every expected record")
        if type(result.get("ready_features")) is not int or result["ready_features"] <= 0:
            raise ValueError("Both replays require positive ready_features")
        digest = result.get("feature_sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Replay feature digest missing")
    if results[0]["feature_sha256"] != results[1]["feature_sha256"]:
        raise ValueError("Replay feature digests disagree")
    def file_signature(data: dict) -> set[tuple]:
        return {(f["file"], f["sha256"], f["bytes"], f["lines"]) for f in data["files"]}
    signatures = [file_signature(item) for item in (audit, *results)]
    if not signatures[0] == signatures[1] == signatures[2]:
        raise ValueError("Replay raw file integrity evidence disagrees")
    if {f["file"]: f["sha256"] for f in results[0]["files"]} != manifest:
        raise ValueError("Replay raw file hashes differ from host manifest")
    return {"feature_sha256": results[0]["feature_sha256"], "files_checked": len(manifest),
            "ready_features": [r["ready_features"] for r in results]}


def check_capture_evidence(directory: Path, previous_session: str) -> dict:
    state = json.loads((directory / "capture-state.json").read_text())
    if state.get("Status") != "exited" or state.get("ExitCode") != 0 or state.get("OOMKilled") is not False:
        raise ValueError("Capture container did not exit cleanly")
    summaries = []
    for line in (directory / "capture.log").read_text().splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and "written_events" in value:
            summaries.append(value)
    if len(summaries) != 1:
        raise ValueError("Expected exactly one completed capture summary")
    samples = [json.loads(line) for line in (directory / "collector-stats.jsonl").read_text().splitlines() if line.strip()]
    if not any(isinstance(item, dict) and isinstance(item.get("MemUsage"), str) and item["MemUsage"] and not item["MemUsage"].startswith("0B") for item in samples):
        raise ValueError("No live resource sample")
    return check_capture(summaries[0], previous_session)


def save_json_exclusive(path: Path, value: dict) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True)
        stream.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    for operation in ("inventory", "verify-prefix", "check-capture", "check-replays"):
        command = sub.add_parser(operation)
        if operation in ("inventory", "verify-prefix"):
            command.add_argument("--raw-dir", type=Path, required=True)
            command.add_argument("--output", type=Path, required=True)
        if operation == "verify-prefix":
            command.add_argument("--inventory", type=Path, required=True)
        if operation in ("check-capture", "check-replays"):
            command.add_argument("--evidence-dir", type=Path, required=True)
        if operation == "check-capture":
            command.add_argument("--previous-session", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.operation == "inventory":
            result = inventory_raw(args.raw_dir)
            save_json_exclusive(args.output, result)
        elif args.operation == "verify-prefix":
            result = verify_raw_prefix(args.raw_dir, json.loads(args.inventory.read_text()))
            save_json_exclusive(args.output, result)
        elif args.operation == "check-capture":
            result = check_capture_evidence(args.evidence_dir, args.previous_session)
            save_json_exclusive(args.evidence_dir / "capture-summary.json", result)
        else:
            directory = args.evidence_dir
            manifest = {}
            for line in (directory / "raw-before.sha256").read_text().splitlines():
                if len(line) < 67 or not re.fullmatch(r"[0-9a-f]{64}", line[:64]) or line[64:66] != "  ":
                    raise ValueError("Invalid raw SHA-256 manifest")
                name = Path(line[66:]).name
                if name in manifest:
                    raise ValueError("Duplicate raw SHA-256 manifest filename")
                manifest[name] = line[:64]
            result = check_replays(json.loads((directory / "raw-audit.json").read_text()),
                                   [json.loads((directory / f"replay-{n}.json").read_text()) for n in (1, 2)],
                                   json.loads((directory / "capture-summary.json").read_text()), manifest)
            save_json_exclusive(directory / "replay-check.json", result)
        print(f"RAW_{args.operation.upper().replace('-', '_')}_OK")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Raw acceptance gate failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
