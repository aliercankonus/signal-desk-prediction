#!/usr/bin/env python3
"""Write one compact, non-destructive task handoff; never calls a model or edits the repo."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

# Reject common credential forms before writing any handoff. This is a safety net,
# not a reason to paste secrets into free-text fields in the first place.
SECRET_RE = re.compile(
    r'(?i)(?:\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|oauth[_-]?token|'
    r'client[_-]?secret|authorization|password)\b\s*[:=]\s*\S+'
    r'|\bbearer\s+[A-Za-z0-9._~+/-]{12,}'
    r'|\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{16,}|github_pat_[A-Za-z0-9_]{16,}'
    r'|ya29\.[A-Za-z0-9._-]{12,})\b)'
)


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--task', required=True, help='Task slug (letters, digits, dots, hyphens, underscores)')
    parser.add_argument('--tests', required=True, help='Exact tests and result, or not run plus reason')
    parser.add_argument('--decisions', required=True)
    parser.add_argument('--remaining', required=True, help='Use none if complete')
    parser.add_argument('--session', default='not recorded', help='Hermes session ID, if known')
    parser.add_argument('--output-root', type=Path, default=Path('/opt/data/development-checkpoints'))
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}', args.task):
        parser.error('invalid task slug')
    repo = args.repo.expanduser().resolve(strict=True)
    root = Path(git(repo, 'rev-parse', '--show-toplevel')).resolve(strict=True)
    branch = git(root, 'branch', '--show-current') or '(detached HEAD)'
    commit = git(root, 'rev-parse', 'HEAD')
    dirty = bool(git(root, 'status', '--porcelain', '--untracked-files=normal'))
    project = root.name + '-' + hashlib.sha256(str(root).encode()).hexdigest()[:10]
    destination = args.output_root.expanduser().resolve() / project / (args.task + '.md')
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Never replace an existing checkpoint, even on failure after the file is opened.
    content = (f'# {args.task}\n\nProject: `{root}`\nSession: `{args.session}`\n'
               f'Branch: `{branch}`\nCommit: `{commit}`\n'
               f'Uncommitted changes: {"yes" if dirty else "no"} (preserved)\n\n'
               f'Tests: {args.tests}\n\nDecisions: {args.decisions}\n\nRemaining: {args.remaining}\n')
    if SECRET_RE.search(content):
        parser.error('checkpoint appears to contain a credential; remove it before saving')
    if len(content) > 8000:
        parser.error('checkpoint exceeds 8000 characters; summarize instead of copying transcripts')
    fd, temp = tempfile.mkstemp(prefix='.checkpoint-', dir=destination.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        # Exclusive create: do not overwrite another task's checkpoint on collision.
        os.link(temp, destination)
    finally:
        os.unlink(temp)
    print(destination)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f'Checkpoint not written: {exc}', file=sys.stderr)
        sys.exit(1)
