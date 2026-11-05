#!/usr/bin/env python3
"""Start a native fresh Hermes task session or explicitly resume one; no API calls here."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HOME = Path('/opt/data')
CHECKPOINTS = HOME / 'development-checkpoints'

SESSION_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z')
TASK = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}\Z')


def repo_root(path: Path) -> Path:
    resolved = path.expanduser().resolve(strict=True)
    result = subprocess.run(
        ['git', '-C', str(resolved), 'rev-parse', '--show-toplevel'],
        capture_output=True, text=True, check=True,
    )
    return Path(result.stdout.strip()).resolve(strict=True)


def project_checkpoints(root: Path) -> Path:
    label = root.name + '-' + hashlib.sha256(str(root).encode()).hexdigest()[:10]
    return CHECKPOINTS / label


def make_task_prompt(root: Path, task: str, brief_path: Path,
                     checkpoint_path: Path | None = None, *, supervised: bool = False) -> str:
    """Build the existing path-only seed for both interactive and supervised tasks."""
    if not TASK.fullmatch(task):
        raise ValueError('invalid task slug')
    brief = Path(brief_path).expanduser().resolve(strict=True)
    if not brief.is_file() or brief.name in ('.env', 'auth.json'):
        raise ValueError('brief must be a regular, non-credential file')
    checkpoint_line = ''
    if checkpoint_path:
        checkpoint = Path(checkpoint_path).expanduser().resolve(strict=True)
        if not checkpoint.is_file() or not checkpoint.is_relative_to(project_checkpoints(root).resolve()):
            raise ValueError('checkpoint must be an existing handoff for this repository')
        checkpoint_line = f'Read only this relevant handoff: {checkpoint}.\n'
    completion = (
        'Do not deploy or restart production services; do not modify auth, providers, or the model. '
        'Do not write a checkpoint yourself; the supervisor independently verifies tests and '
        'writes it. End with ONLY a JSON object with keys status (complete or incomplete), '
        'decisions (short, credential-free), and remaining (none or a short explanation). '
        'Only use complete when your work is done; do not claim tests you did not run.'
        if supervised else
        'At completion, write a compact task checkpoint using '
        '/opt/data/autonomous-development/checkpoint.py with actual test results, decisions, '
        'and remaining work. Never put credentials or transcripts in it.'
    )
    return (
        f'Independent development task {task}. Read the task brief: {brief}.\n'
        f'{checkpoint_line}'
        'Inspect the current Git branch, HEAD, and uncommitted work before editing. '
        'Keep related subtasks in this session. Implement and test the task autonomously; '
        'preserve unrelated changes. ' + completion
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    start = sub.add_parser('start', help='New, independent conversation (never resumes by task name)')
    start.add_argument('--repo', type=Path, required=True)
    start.add_argument('--task', required=True, help='Short new task slug')
    start.add_argument('--brief', type=Path, required=True, help='Existing task brief file; only its path is sent in the seed')
    start.add_argument('--checkpoint', type=Path, help='A selected handoff from this repo; no other checkpoints loaded')
    resume = sub.add_parser('resume', help='Explicitly resume an existing Hermes session by ID')
    resume.add_argument('--repo', type=Path, required=True)
    resume.add_argument('--session', required=True)
    for p in (start, resume):
        p.add_argument('--interface', choices=('tui', 'cli'), default='tui')
        p.add_argument('--dry-run', action='store_true', help='Validate and show launch arguments; never launch Hermes')
    args = parser.parse_args()
    if args.action == 'start' and not TASK.fullmatch(args.task):
        parser.error('invalid task slug')
    if args.action == 'resume' and not SESSION_ID.fullmatch(args.session):
        parser.error('invalid session ID')
    return args


def main() -> int:
    args = parse_args()
    if Path(os.environ.get('HERMES_HOME', str(HOME))).resolve() != HOME:
        raise ValueError('This workflow targets /opt/data only; HERMES_HOME points elsewhere')
    root = repo_root(args.repo)
    argv = ['hermes', 'chat', '--in', str(root), '--' + args.interface]
    prompt = None
    if args.action == 'resume':
        argv.extend(['--resume', args.session])
    else:
        prompt = make_task_prompt(root, args.task, args.brief, args.checkpoint)
    if prompt:
        # The TUI launch path passes -q through to HERMES_TUI_QUERY but does NOT
        # read --query-file (main.py returns to _launch_tui first). The argument
        # contains paths and guidance only, not the brief/checkpoint contents.
        argv.extend(['-q', prompt])
    if args.dry_run:
        print(json.dumps({'argv': argv,
                          'repo': str(root), 'fresh': args.action == 'start',
                          'seed': prompt}, indent=2))
        return 0
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ValueError('Interactive TTY required; refusing a non-TTY seeded one-shot/API call')
    if prompt is None:
        print(f'Resuming session {args.session} in {root}', file=sys.stderr)
        return subprocess.run(argv, cwd=root, check=False).returncode
    print(f'Starting fresh task {args.task} in {root} (no --resume/--continue)', file=sys.stderr)
    return subprocess.run(argv, cwd=root, check=False).returncode


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f'Task session not started: {exc}', file=sys.stderr)
        sys.exit(2)
