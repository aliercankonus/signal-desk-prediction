#!/usr/bin/env python3
"""Read-only verification of the frozen #41 review inputs; never activates a run."""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess


PIN = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
REPO = "aliercankonus/signal-desk-prediction"


def verify(root: Path, manifest_file: Path, issue_body: Path | None = None) -> int:
    if manifest_file.stat().st_size > 65536:
        raise ValueError("oversized manifest")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if manifest.get("schema") != 1 or manifest.get("repository") != REPO:
        raise ValueError("wrong manifest schema/repository")
    pin = manifest.get("reviewed_main")
    if not isinstance(pin, str) or not PIN.fullmatch(pin):
        raise ValueError("invalid reviewed commit")
    if manifest.get("candidate_runner") != pin or manifest.get("candidate_task_start") != pin:
        raise ValueError("runner/start transition changed; new review required")
    files = manifest.get("frozen_source_sha256")
    if not isinstance(files, dict) or not 1 <= len(files) <= 64:
        raise ValueError("invalid source manifest")
    root = root.resolve(strict=True)
    count = 0
    for name, expected in sorted(files.items()):
        if not isinstance(name, str) or not isinstance(expected, str) or not DIGEST.fullmatch(expected):
            raise ValueError("invalid source entry")
        path = PurePosixPath(name)
        if (path.is_absolute() or not path.parts or any(x in (".", "..") for x in path.parts)
                or path.as_posix() != name):
            raise ValueError("unsafe source path")
        local = root.joinpath(*path.parts)
        if not local.is_file() or local.is_symlink() or local.resolve() != local:
            raise ValueError("missing/symlinked source file: " + name)
        if local.stat().st_size > 262144:
            raise ValueError("oversized source file: " + name)
        if hashlib.sha256(local.read_bytes()).hexdigest() != expected:
            raise ValueError("working source differs: " + name)
        observed = subprocess.run(
            ["git", "-C", str(root), "show", f"{pin}:{name}"],
            capture_output=True, check=True, timeout=20,
        ).stdout
        if hashlib.sha256(observed).hexdigest() != expected:
            raise ValueError("reviewed Git object differs: " + name)
        count += 1
    candidates = manifest.get("candidate_files_sha256")
    if not isinstance(candidates, dict) or set(candidates) != {
        "ops/bridge_one_shot/bridge_once_candidate.py",
        "ops/bridge_one_shot/compose.candidate.yml",
    }:
        raise ValueError("candidate file set changed")
    for name, expected in sorted(candidates.items()):
        if not isinstance(expected, str) or not DIGEST.fullmatch(expected):
            raise ValueError("invalid candidate digest")
        local = root / name
        if not local.is_file() or local.is_symlink() or local.resolve() != local:
            raise ValueError("missing/symlinked candidate file")
        if local.stat().st_size > 262144:
            raise ValueError("oversized candidate file")
        if hashlib.sha256(local.read_bytes()).hexdigest() != expected:
            raise ValueError("candidate file changed: " + name)
        count += 1
    if issue_body is not None:
        expected = manifest.get("task_body_sha256")
        if not isinstance(expected, str) or not DIGEST.fullmatch(expected):
            raise ValueError("invalid task-body digest")
        if issue_body.stat().st_size > 65536:
            raise ValueError("oversized task issue body")
        if hashlib.sha256(issue_body.read_bytes()).hexdigest() != expected:
            raise ValueError("frozen task issue body differs")
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--manifest", type=Path, default=Path(__file__).with_name("review_manifest.json"))
    parser.add_argument("--issue-body", type=Path, help="optional exact UTF-8 #43 body file, obtained separately")
    args = parser.parse_args()
    try:
        count = verify(args.repo, args.manifest, args.issue_body)
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print("STOP: read-only review verification failed (" + type(exc).__name__ + ")")
        return 2
    print(f"REVIEW ONLY: {count} source blobs match pinned Git objects and local bytes; no activation")
    if args.issue_body is None:
        print("Task #43 body digest not checked; pass --issue-body after independent GitHub readback")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
